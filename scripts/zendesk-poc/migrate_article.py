#!/usr/bin/env python3
"""
Contacts+ Zendesk → Docmost migration POC (single article).

Fetches one public Help Center article, cleans HTML, downloads images,
and packages output for Docmost Generic ZIP Import.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import zipfile
from pathlib import Path
from urllib.parse import unquote, urlparse

import requests
from bs4 import BeautifulSoup, NavigableString, Tag

ARTICLE_ID = 4407112098587
LOCALE = "en-us"
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def fetch_article(article_id: int) -> dict:
    url = (
        f"https://support.contactsplus.com/api/v2/help_center/"
        f"{LOCALE}/articles/{article_id}.json"
    )
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    payload = response.json()
    article = payload.get("article")
    if not article:
        raise ValueError(f"No article found for ID {article_id}")
    return article


def sanitize_filename(name: str) -> str:
    cleaned = re.sub(r"[^\w.\-]+", "-", name.strip())
    cleaned = re.sub(r"-+", "-", cleaned).strip("-")
    return cleaned or "image"


def filename_from_url(url: str) -> str:
    path = unquote(urlparse(url).path)
    basename = Path(path).name
    if basename:
        return sanitize_filename(basename)
    return "image.png"


def unwrap_tag(tag: Tag) -> None:
    tag.unwrap()


def is_empty_element(tag: Tag) -> bool:
    if tag.name in {"br", "hr", "img"}:
        return False
    
    # Check if tag is still valid/attached
    if not hasattr(tag, 'attrs') or tag.attrs is None:
        return True
    
    # Preserve Docmost media nodes (embeds, attachments, etc.)
    data_type = tag.get("data-type")
    if data_type in {"embed", "video", "audio", "attachment", "drawio", "excalidraw"}:
        return False
    
    text = tag.get_text(strip=True)
    if text:
        return False
    return not tag.find(["img", "video", "audio", "iframe", "svg"])


def remove_empty_elements(soup: BeautifulSoup) -> None:
    changed = True
    while changed:
        changed = False
        for tag in list(soup.find_all(True)):
            if tag.name in {"html", "body", "[document]"}:
                continue
            
            # Skip if tag became invalid during iteration
            if not hasattr(tag, 'name') or not hasattr(tag, 'attrs'):
                continue
                
            if is_empty_element(tag):
                tag.decompose()
                changed = True


def strip_attributes(tag: Tag, allowed: set[str] | None = None) -> None:
    if allowed is None:
        tag.attrs = {}
        return
    tag.attrs = {key: value for key, value in tag.attrs.items() if key in allowed}


def convert_pseudo_headings(soup: BeautifulSoup) -> None:
    for tag in list(soup.find_all(["span", "p", "div"])):
        classes = tag.get("class") or []
        if "wysiwyg-font-size-large" not in classes:
            continue

        strong = tag.find("strong")
        if not strong:
            continue

        heading_text = strong.get_text(strip=True)
        if not heading_text:
            continue

        heading = soup.new_tag("h2")
        heading.string = heading_text
        tag.replace_with(heading)


def normalize_lists(soup: BeautifulSoup) -> None:
    for li in soup.find_all("li"):
        if "data-list-item-id" in li.attrs:
            del li.attrs["data-list-item-id"]
        strip_attributes(li)


def normalize_links(soup: BeautifulSoup) -> None:
    for anchor in soup.find_all("a"):
        href = anchor.get("href")
        if not href:
            anchor.unwrap()
            continue
        strip_attributes(anchor, {"href"})
        if anchor.get("target"):
            del anchor["target"]
        if anchor.get("rel"):
            del anchor["rel"]


def normalize_images(soup: BeautifulSoup) -> None:
    for img in soup.find_all("img"):
        allowed = {"src", "alt", "width", "height"}
        strip_attributes(img, allowed)
        for attr in ("class", "style"):
            if attr in img.attrs:
                del img[attr]


def remove_zendesk_wrappers(soup: BeautifulSoup) -> None:
    selectors = [
        "section.hs-wysiwyg",
        "section#lockbarContainer",
        "section#stillEditingContainer",
        "section.lockBar",
        "div.redactor",
    ]
    for selector in selectors:
        for tag in soup.select(selector):
            if tag.name == "div" and tag.get("id") == "redactor":
                unwrap_tag(tag)
            elif is_empty_element(tag):
                tag.decompose()
            else:
                unwrap_tag(tag)

    for tag in soup.find_all(["section", "div"]):
        if tag.get("id") in {"lockbarContainer", "stillEditingContainer", "redactor"}:
            unwrap_tag(tag)
        classes = tag.get("class") or []
        if any(
            cls in classes
            for cls in (
                "hs-wysiwyg",
                "articleTabContent",
                "lockBar",
                "redactor",
                "wysiwyg-font-size-large",
                "wysiwyg-text-align-center",
                "wysiwyg-image-resized",
            )
        ):
            if tag.name == "p" and "wysiwyg-text-align-center" in classes:
                strip_attributes(tag)
            elif "wysiwyg-font-size-large" in classes:
                continue
            elif tag.name in {"section", "div"} and not tag.get_text(strip=True):
                tag.decompose()
            elif tag.name in {"section", "div"}:
                unwrap_tag(tag)
            else:
                strip_attributes(tag)


def owning_soup(tag: Tag) -> BeautifulSoup:
    element: Tag | BeautifulSoup = tag
    while element.parent is not None:
        element = element.parent
    return element  # type: ignore[return-value]


def br_to_paragraphs(tag: Tag) -> list[Tag]:
    paragraphs: list[Tag] = []
    current_lines: list[str] = []
    soup = owning_soup(tag)

    def flush() -> None:
        text = " ".join(line.strip() for line in current_lines if line.strip())
        if text:
            paragraph = soup.new_tag("p")
            paragraph.string = text
            paragraphs.append(paragraph)
        current_lines.clear()

    for child in tag.children:
        if isinstance(child, Tag) and child.name == "br":
            flush()
            continue
        chunk = child.get_text() if isinstance(child, Tag) else str(child)
        if chunk.strip():
            current_lines.append(chunk.strip())

    flush()
    return paragraphs


def split_br_paragraphs(soup: BeautifulSoup) -> None:
    for paragraph in list(soup.find_all("p")):
        if paragraph.find(["ul", "ol", "img", "h1", "h2", "h3", "h4"]):
            continue

        br_count = len(paragraph.find_all("br"))
        if br_count >= 2:
            replacement = br_to_paragraphs(paragraph)
            if replacement:
                paragraph.replace_with(*replacement)
            else:
                paragraph.decompose()
            continue

        text = paragraph.get_text(strip=True)
        if not text:
            paragraph.decompose()
            continue

        for br in paragraph.find_all("br"):
            br.decompose()
        if paragraph.get_text(strip=True) != text:
            paragraph.clear()
            paragraph.append(text)


def normalize_orphan_br_blocks(soup: BeautifulSoup) -> None:
    block_tags = {"p", "h1", "h2", "h3", "h4", "ul", "ol", "div", "img"}

    for heading in list(soup.find_all(["h2", "h3", "h4"])):
        inline_nodes = []
        sibling = heading.next_sibling

        while sibling is not None:
            if isinstance(sibling, Tag) and sibling.name in block_tags:
                break
            inline_nodes.append(sibling)
            sibling = sibling.next_sibling

        if not inline_nodes:
            continue

        wrapper = owning_soup(heading).new_tag("div")
        for node in inline_nodes:
            wrapper.append(node.extract())

        paragraphs = br_to_paragraphs(wrapper)
        if paragraphs:
            heading.insert_after(*paragraphs)


def promote_div_text_blocks(soup: BeautifulSoup) -> None:
    for div in list(soup.find_all("div")):
        if div.find(["div", "p", "ul", "ol", "h1", "h2", "h3", "h4", "img"]):
            continue
        if div.find("br"):
            replacement = br_to_paragraphs(div)
            if replacement:
                div.replace_with(*replacement)
            else:
                div.decompose()
            continue
        text = div.get_text(" ", strip=True)
        if not text:
            div.decompose()
            continue
        paragraph = owning_soup(div).new_tag("p")
        paragraph.string = text
        div.replace_with(paragraph)


def flatten_inline_styles(soup: BeautifulSoup) -> None:
    """Remove style/class attributes, but preserve data-type/data-* on embed nodes."""
    for tag in soup.find_all(True):
        if "style" in tag.attrs:
            del tag["style"]
        if "class" in tag.attrs:
            del tag["class"]
        
        # Preserve data-* attributes on Docmost embed/media nodes
        if tag.get("data-type") in {"embed", "video", "audio", "attachment", "drawio"}:
            continue
        
        for attr in list(tag.attrs):
            if attr.startswith("data-"):
                del tag[attr]


def convert_loom_iframes_to_embeds(soup: BeautifulSoup) -> tuple[int, int]:
    """
    Convert Loom/YouTube/Vimeo iframes to Docmost embed nodes.
    Returns (loom_count, unsupported_count).
    """
    loom_count = 0
    unsupported_count = 0
    
    loom_pattern = re.compile(
        r'^(?:https?:)?//(?:www\.)?loom\.com/(?:share|embed)/([\da-zA-Z_-]+)',
        re.IGNORECASE
    )
    youtube_pattern = re.compile(
        r'^(?:https?:)?//(?:www\.)?(?:youtube\.com/embed|youtu\.be)/([\w-]+)',
        re.IGNORECASE
    )
    vimeo_pattern = re.compile(
        r'^(?:https?:)?//(?:www\.|player\.)?vimeo\.com/(?:video/)?(\d+)',
        re.IGNORECASE
    )
    
    for iframe in list(soup.find_all('iframe')):
        src = (iframe.get('src') or '').strip()
        if not src:
            iframe.decompose()
            continue
        
        provider = None
        embed_url = None
        
        # Check Loom
        match = loom_pattern.match(src)
        if match:
            video_id = match.group(1)
            embed_url = f"https://loom.com/embed/{video_id}"
            provider = "loom"
            loom_count += 1
        
        # Check YouTube
        if not provider:
            match = youtube_pattern.match(src)
            if match:
                video_id = match.group(1)
                embed_url = f"https://www.youtube-nocookie.com/embed/{video_id}"
                provider = "youtube"
        
        # Check Vimeo
        if not provider:
            match = vimeo_pattern.match(src)
            if match:
                video_id = match.group(1)
                embed_url = f"https://player.vimeo.com/video/{video_id}"
                provider = "vimeo"
        
        if provider and embed_url:
            # Extract dimensions from iframe
            width = iframe.get('width', '800')
            height = iframe.get('height', '600')
            
            # Normalize dimensions
            try:
                width = str(int(width)) if str(width).isdigit() else '800'
            except (ValueError, TypeError):
                width = '800'
            
            try:
                height = str(int(height)) if str(height).isdigit() else '600'
            except (ValueError, TypeError):
                height = '600'
            
            # Create Docmost embed div
            embed_div = soup.new_tag('div')
            embed_div['data-type'] = 'embed'
            embed_div['data-src'] = embed_url
            embed_div['data-provider'] = provider
            embed_div['data-align'] = 'center'
            embed_div['data-width'] = width
            embed_div['data-height'] = height
            
            iframe.replace_with(embed_div)
            
            # If embed is inside a <p> tag that only contains this embed, unwrap the p
            if embed_div.parent and embed_div.parent.name == 'p':
                parent_text = embed_div.parent.get_text(strip=True)
                if not parent_text:  # p contains only the embed
                    embed_div.parent.unwrap()
        else:
            # Unsupported iframe - convert to link
            # Normalize protocol-relative URLs
            if src.startswith('//'):
                src = 'https:' + src
            link = soup.new_tag('a', href=src)
            link.string = f"[Embedded content: {src}]"
            iframe.replace_with(link)
            unsupported_count += 1
    
    return loom_count, unsupported_count


def clean_html(raw_html: str) -> tuple[str, dict]:
    """
    Minimally clean HTML while preserving semantic structure.
    Returns (cleaned_html, stats_dict).
    """
    soup = BeautifulSoup(raw_html, "lxml")
    body = soup.body or soup

    # Remove executable/presentation-only elements.
    for tag in list(body.find_all(["script", "style"])):
        tag.decompose()
    
    # Convert iframes to embeds BEFORE other cleaning
    loom_count, unsupported_count = convert_loom_iframes_to_embeds(body)

    # Preserve semantic content while removing editor-specific attributes.
    normalize_links(body)
    normalize_lists(body)
    normalize_images(body)
    flatten_inline_styles(body)
    remove_empty_elements(body)

    stats = {
        "loom_embeds": loom_count,
        "unsupported_iframes": unsupported_count,
    }

    # Keep useful semantic tags and their content; avoid creating/replacing
    # nodes with new_tag(), which caused detached-tree failures in the POC.
    if soup.body:
        return soup.body.decode_contents().strip(), stats
    return body.decode_contents().strip(), stats


def extract_remote_images(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    urls: list[str] = []
    for img in soup.find_all("img"):
        src = (img.get("src") or "").strip()
        if src.startswith(("http://", "https://")):
            urls.append(src)
    return urls


def download_images(urls: list[str], assets_dir: Path) -> dict[str, str]:
    """
    Download images and infer extension from Content-Type if URL has none.
    Returns mapping of remote_url -> local_path.
    """
    assets_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    
    mime_to_ext = {
        'image/png': '.png',
        'image/jpeg': '.jpg',
        'image/jpg': '.jpg',
        'image/gif': '.gif',
        'image/webp': '.webp',
        'image/svg+xml': '.svg',
        'image/bmp': '.bmp',
        'image/tiff': '.tif',
    }

    for index, url in enumerate(urls, start=1):
        try:
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            
            # Try to get filename from URL first
            filename = filename_from_url(url)
            
            # If no extension, check Content-Type header
            if '.' not in filename or filename.endswith('.'):
                content_type = response.headers.get('Content-Type', '').split(';')[0].strip().lower()
                ext = mime_to_ext.get(content_type, '.png')
                
                # Use numeric ID from URL if available, otherwise generic name
                if filename and filename != 'image':
                    filename = f"{filename}{ext}"
                else:
                    # Extract numeric ID from URL path
                    path_parts = urlparse(url).path.split('/')
                    numeric_id = next((part for part in reversed(path_parts) if part.isdigit()), None)
                    if numeric_id:
                        filename = f"{numeric_id}{ext}"
                    else:
                        filename = f"image-{index}{ext}"
            
            destination = assets_dir / filename
            
            # Handle duplicates
            if destination.exists():
                stem = destination.stem
                suffix = destination.suffix
                destination = assets_dir / f"{stem}-{index}{suffix}"
            
            destination.write_bytes(response.content)
            mapping[url] = f"assets/{destination.name}"
        
        except requests.RequestException as exc:
            print(f"Warning: Failed to download {url}: {exc}", file=sys.stderr)
            continue

    return mapping


def rewrite_image_sources(html: str, url_map: dict[str, str]) -> str:
    soup = BeautifulSoup(html, "lxml")
    body = soup.body or soup

    for img in body.find_all("img"):
        src = (img.get("src") or "").strip()
        if src in url_map:
            img["src"] = url_map[src]

    if soup.body:
        return soup.body.decode_contents().strip()
    return str(body).strip()


def build_docmost_html(cleaned_body: str, metadata: dict) -> str:
    title = metadata["title"]
    comment_lines = [
        f"Source URL: {metadata['source_url']}",
        f"Section ID: {metadata['section_id']}",
        f"Updated at: {metadata['updated_at']}",
        f"Zendesk article ID: {metadata['article_id']}",
    ]
    comment = "\n".join(f"  {line}" for line in comment_lines)
    return (
        "<!DOCTYPE html>\n"
        f"<html>\n<head>\n  <meta charset=\"utf-8\">\n"
        f"  <title>{title}</title>\n  <!--\n{comment}\n  -->\n"
        f"</head>\n<body>\n{cleaned_body}\n</body>\n</html>\n"
    )


def create_zip(source_dir: Path, zip_path: Path) -> None:
    include_names = {path.name for path in source_dir.glob("*.html")}
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if not path.is_file():
                continue
            rel = path.relative_to(source_dir)
            if rel.parts[0] == "assets" or path.name in include_names:
                archive.write(path, arcname=rel.as_posix())


def run(article_id: int, output_dir: Path) -> dict:
    article = fetch_article(article_id)

    metadata = {
        "article_id": article["id"],
        "title": article.get("title") or article.get("name") or "Untitled",
        "source_url": article.get("html_url"),
        "section_id": article.get("section_id"),
        "updated_at": article.get("updated_at"),
        "api_url": article.get("url"),
    }

    raw_body = article.get("body") or ""
    cleaned_body, clean_stats = clean_html(raw_body)
    image_urls = extract_remote_images(cleaned_body)

    article_dir = output_dir / sanitize_filename(metadata["title"])
    assets_dir = article_dir / "assets"
    article_dir.mkdir(parents=True, exist_ok=True)

    url_map = download_images(image_urls, assets_dir)
    final_body = rewrite_image_sources(cleaned_body, url_map)

    html_filename = f"{metadata['title']}.html"
    html_path = article_dir / html_filename
    html_path.write_text(build_docmost_html(final_body, metadata), encoding="utf-8")

    metadata_path = article_dir / "article-metadata.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    zip_path = output_dir / f"{sanitize_filename(metadata['title'])}.zip"
    create_zip(article_dir, zip_path)

    return {
        "metadata": metadata,
        "article_dir": article_dir,
        "html_path": html_path,
        "zip_path": zip_path,
        "image_urls": image_urls,
        "url_map": url_map,
        "cleaned_body": final_body,
        "clean_stats": clean_stats,
    }


def print_summary(result: dict) -> None:
    metadata = result["metadata"]
    article_dir = result["article_dir"]
    clean_stats = result.get("clean_stats", {})

    print("\n=== Files created ===")
    for path in sorted(article_dir.rglob("*")):
        if path.is_file():
            print(f"  {path}")
    print(f"  {result['zip_path']}")

    print("\n=== Article metadata ===")
    for key, value in metadata.items():
        print(f"  {key}: {value}")
    
    print("\n=== Embedded media ===")
    print(f"  Loom embeds converted: {clean_stats.get('loom_embeds', 0)}")
    print(f"  Unsupported iframes converted to links: {clean_stats.get('unsupported_iframes', 0)}")

    print("\n=== Downloaded images ===")
    if result["url_map"]:
        for remote, local in result["url_map"].items():
            print(f"  {local}  <=  {remote}")
    else:
        print("  (none)")

    print("\n=== Cleaned HTML structure ===")
    soup = BeautifulSoup(result["cleaned_body"], "lxml")
    body = soup.body or soup
    
    # Show embed nodes explicitly
    for embed in body.find_all('div', attrs={'data-type': 'embed'}):
        provider = embed.get('data-provider', 'unknown')
        src = embed.get('data-src', '')
        print(f"  <div data-type=\"embed\" data-provider=\"{provider}\" data-src=\"{src[:60]}...\">")
    
    for element in body.find_all(["h2", "p", "ul", "ol", "li", "img", "a"], recursive=False):
        preview = element.get_text(" ", strip=True)
        if element.name == "img":
            print(f"  <img src=\"{element.get('src')}\">")
        elif element.name == "a":
            print(f"  <a href=\"{element.get('href')}\">{preview}</a>")
        elif preview:
            snippet = preview[:100] + ("..." if len(preview) > 100 else "")
            print(f"  <{element.name}> {snippet}")

    print("\n=== ZIP contents ===")
    with zipfile.ZipFile(result["zip_path"], "r") as archive:
        for name in archive.namelist():
            info = archive.getinfo(name)
            print(f"  {name} ({info.file_size} bytes)")

    print("\n=== Transformations applied ===")
    print("  - Fetched article from public Contacts+ Zendesk Help Center API")
    print("  - Converted Loom/YouTube/Vimeo iframes to Docmost embed nodes")
    print("  - Applied minimal HTML cleanup without pseudo-heading conversion")
    print("  - Preserved semantic HTML, links, lists, and paragraph structure")
    print("  - Stripped classes, inline styles (except data-* on embed nodes)")
    print("  - Downloaded remote images with Content-Type-based extension inference")
    print("  - Packaged HTML + assets into a Generic ZIP Import-compatible archive")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate one Contacts+ Zendesk article to Docmost Generic ZIP format."
    )
    parser.add_argument(
        "--article-id",
        type=int,
        default=ARTICLE_ID,
        help=f"Zendesk article ID (default: {ARTICLE_ID})",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for generated HTML, assets, and ZIP",
    )
    args = parser.parse_args()

    try:
        result = run(args.article_id, args.output_dir)
    except requests.RequestException as exc:
        print(f"Network error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 - POC script reports all failures clearly
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1

    print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
