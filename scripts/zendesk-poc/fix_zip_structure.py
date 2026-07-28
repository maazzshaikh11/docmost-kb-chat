#!/usr/bin/env python3
"""
Fix ZIP structure for Docmost Generic ZIP Import.

Current structure (wrong):
  Section/Article-Dir/Article.html
  Section/Article-Dir/assets/image.png

Correct structure:
  Section/Article.html  
  Section/Article_files/image.png

This creates:
  Section (page) -> Article (child page with content)

Instead of:
  Section (page) -> Article-Dir (empty page) -> Article (child page with content)
"""

import re
import shutil
import zipfile
from pathlib import Path

from bs4 import BeautifulSoup


def create_test_zip():
    """Create a small test ZIP with 3 articles for verification."""
    print("\n" + "="*80)
    print("CREATING TEST ZIP")
    print("="*80 + "\n")
    
    source_dir = Path("output/full_migration")
    test_dir = Path("output/test_import")
    test_dir.mkdir(parents=True, exist_ok=True)
    
    # Select 3 test articles:
    # 1. With images
    # 2. With Loom embed
    # 3. Simple text
    test_articles = [
        ("Contacts-Basics", "Contacts-for-Web"),  # Has 6 images
        ("Get-to-Know-Contacts", "Getting-Started"),  # Has 3 Loom embeds
        ("Account-and-Billing", "Refund-Policy"),  # Simple text
    ]
    
    for section, article in test_articles:
        section_src = source_dir / section / article
        if not section_src.exists():
            print(f"WARNING: {section_src} not found, skipping")
            continue
        
        # Find the HTML file
        html_files = list(section_src.glob("*.html"))
        if not html_files:
            print(f"WARNING: No HTML file in {section_src}, skipping")
            continue
        
        html_file = html_files[0]
        
        # Create section directory in test output
        section_dest = test_dir / section
        section_dest.mkdir(parents=True, exist_ok=True)
        
        # Copy HTML file directly to section directory
        html_dest = section_dest / html_file.name
        shutil.copy2(html_file, html_dest)
        
        print(f"Copied: {section}/{html_file.name}")
        
        # Check for assets
        assets_src = section_src / "assets"
        if assets_src.exists():
            # Create Article_files directory
            article_files_name = html_file.stem + "_files"
            assets_dest = section_dest / article_files_name
            assets_dest.mkdir(parents=True, exist_ok=True)
            
            # Copy all assets
            asset_count = 0
            for asset in assets_src.iterdir():
                if asset.is_file():
                    shutil.copy2(asset, assets_dest / asset.name)
                    asset_count += 1
            
            print(f"  Assets: {asset_count} files -> {article_files_name}/")
            
            # Update HTML to reference Article_files/image.png instead of assets/image.png
            html_content = html_dest.read_text(encoding='utf-8')
            html_content = html_content.replace('src="assets/', f'src="{article_files_name}/')
            html_dest.write_text(html_content, encoding='utf-8')
            
            print(f"  Updated asset references in HTML")
    
    # Create test ZIP
    test_zip_path = Path("output/Test_Import.zip")
    with zipfile.ZipFile(test_zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(test_dir.rglob("*")):
            if path.is_file():
                rel_path = path.relative_to(test_dir)
                archive.write(path, arcname=rel_path.as_posix())
                print(f"  Added to ZIP: {rel_path}")
    
    print(f"\nTest ZIP created: {test_zip_path}")
    print(f"Size: {test_zip_path.stat().st_size / 1024:.2f} KB")
    
    # List ZIP contents
    print(f"\nZIP Structure:")
    with zipfile.ZipFile(test_zip_path, 'r') as archive:
        for name in sorted(archive.namelist()):
            print(f"  {name}")
    
    return test_zip_path


def create_full_zip():
    """Create the full migration ZIP with correct structure."""
    print("\n" + "="*80)
    print("CREATING FULL MIGRATION ZIP WITH CORRECT STRUCTURE")
    print("="*80 + "\n")
    
    source_dir = Path("output/full_migration")
    fixed_dir = Path("output/fixed_migration")
    fixed_dir.mkdir(parents=True, exist_ok=True)
    
    article_count = 0
    asset_count = 0
    
    # Process each section
    for section_dir in sorted(source_dir.iterdir()):
        if not section_dir.is_dir():
            continue
        
        section_name = section_dir.name
        print(f"\nProcessing section: {section_name}")
        
        # Create section in fixed output
        fixed_section = fixed_dir / section_name
        fixed_section.mkdir(parents=True, exist_ok=True)
        
        # Process each article in the section
        for article_dir in sorted(section_dir.iterdir()):
            if not article_dir.is_dir():
                continue
            
            # Find HTML file
            html_files = list(article_dir.glob("*.html"))
            if not html_files:
                print(f"  WARNING: No HTML in {article_dir.name}")
                continue
            
            html_file = html_files[0]
            article_count += 1
            
            # Copy HTML directly to section directory
            html_dest = fixed_section / html_file.name
            shutil.copy2(html_file, html_dest)
            
            # Handle assets
            assets_src = article_dir / "assets"
            if assets_src.exists() and assets_src.is_dir():
                # Create Article_files directory
                article_files_name = html_file.stem + "_files"
                assets_dest = fixed_section / article_files_name
                assets_dest.mkdir(parents=True, exist_ok=True)
                
                # Copy assets
                local_asset_count = 0
                for asset in assets_src.iterdir():
                    if asset.is_file():
                        shutil.copy2(asset, assets_dest / asset.name)
                        local_asset_count += 1
                        asset_count += 1
                
                # Update HTML references
                html_content = html_dest.read_text(encoding='utf-8')
                html_content = html_content.replace('src="assets/', f'src="{article_files_name}/')
                html_dest.write_text(html_content, encoding='utf-8')
                
                print(f"  {html_file.name} + {local_asset_count} assets")
            else:
                print(f"  {html_file.name}")
    
    print(f"\n{'='*80}")
    print(f"Restructured: {article_count} articles, {asset_count} assets")
    print(f"{'='*80}\n")
    
    # Create final ZIP
    zip_path = Path("output/Contacts_Plus_KB_Import.zip")
    with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(fixed_dir.rglob("*")):
            if path.is_file():
                rel_path = path.relative_to(fixed_dir)
                archive.write(path, arcname=rel_path.as_posix())
    
    print(f"Final ZIP created: {zip_path}")
    print(f"Size: {zip_path.stat().st_size / (1024*1024):.2f} MB")
    
    # Validate
    print(f"\n{'='*80}")
    print("VALIDATION")
    print(f"{'='*80}\n")
    
    with zipfile.ZipFile(zip_path, 'r') as archive:
        files = archive.namelist()
        html_files = [f for f in files if f.endswith('.html')]
        asset_files = [f for f in files if any(f.endswith(ext) for ext in ['.png', '.jpg', '.gif', '.webp', '.svg'])]
        
        print(f"Total files in ZIP: {len(files)}")
        print(f"HTML files: {len(html_files)}")
        print(f"Asset files: {len(asset_files)}")
        
        # Check structure
        print(f"\nStructure validation:")
        
        # Count sections
        sections = set()
        for f in html_files:
            parts = f.split('/')
            if len(parts) >= 1:
                sections.add(parts[0])
        
        print(f"  Sections: {len(sections)}")
        
        # Verify no triple-nested structure
        triple_nested = [f for f in html_files if f.count('/') > 1]
        if triple_nested:
            print(f"  WARNING: {len(triple_nested)} HTML files are nested too deep!")
            for f in triple_nested[:5]:
                print(f"    {f}")
        else:
            print(f"  ✓ All HTML files are at Section/Article.html level")
        
        # Sample structure
        print(f"\nSample ZIP structure:")
        for f in sorted(files)[:20]:
            print(f"  {f}")
        if len(files) > 20:
            print(f"  ... and {len(files) - 20} more")
    
    # Test ZIP integrity
    print(f"\nZIP integrity test:")
    try:
        with zipfile.ZipFile(zip_path, 'r') as archive:
            bad_file = archive.testzip()
            if bad_file:
                print(f"  ✗ FAILED: {bad_file} is corrupted")
            else:
                print(f"  ✓ OK - All files valid")
    except Exception as e:
        print(f"  ✗ ERROR: {e}")
    
    print(f"\n{'='*80}\n")
    
    return zip_path


def main():
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Fix ZIP structure for Docmost import"
    )
    parser.add_argument(
        "--test-only",
        action="store_true",
        help="Create only the test ZIP with 3 articles",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Create the full migration ZIP",
    )
    
    args = parser.parse_args()
    
    if args.test_only or not args.full:
        test_zip = create_test_zip()
        print(f"\n{'='*80}")
        print("NEXT STEPS")
        print(f"{'='*80}\n")
        print("1. Import the test ZIP into Docmost")
        print("2. Verify the hierarchy is:")
        print("   - Contacts Basics (section page)")
        print("     - Contacts+ for Web (article with 6 images)")
        print("   - Get to Know Contacts+ (section page)")
        print("     - Getting Started (article with 3 Loom embeds)")
        print("   - Account and Billing (section page)")
        print("     - Refund Policy (article with text)")
        print("3. Confirm NO empty intermediate pages")
        print("4. If correct, run with --full flag")
        print(f"\n{'='*80}\n")
    
    if args.full:
        full_zip = create_full_zip()
        print("Full migration ZIP ready for import!")


if __name__ == "__main__":
    main()
