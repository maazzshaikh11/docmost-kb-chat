import re

def process_citations(answer: str, unique_sources: list, debug: bool = False) -> tuple[str, list]:
    """
    Normalizes citations, filters unused sources, and remaps citation numbers.
    """
    original_answer = answer
    
    # 1. Normalize spacing: `[1] [2]` -> `[1][2]`
    answer = re.sub(r'\]\s+\[', '][', answer)
    
    # 2. Normalize duplicates: `[1][1]` -> `[1]`
    while True:
        new_answer = re.sub(r'\[(\d+)\]\[\1\]', r'[\1]', answer)
        if new_answer == answer:
            break
        answer = new_answer
        
    # 3. Find used citations
    used_numbers = set()
    for match in re.finditer(r'\[(\d+)\]', answer):
        used_numbers.add(int(match.group(1)))
        
    used_numbers = sorted(list(used_numbers))
    
    # 4. Filter and remap
    remap = {}
    final_sources = []
    
    for new_idx, old_num in enumerate(used_numbers):
        source_idx = old_num - 1
        if 0 <= source_idx < len(unique_sources):
            remap[str(old_num)] = str(new_idx + 1)
            final_sources.append(unique_sources[source_idx])
            
    # 5. Apply remapping
    def repl(match):
        old_num_str = match.group(1)
        if old_num_str in remap:
            return f"[{remap[old_num_str]}]"
        return match.group(0)
        
    final_answer = re.sub(r'\[(\d+)\]', repl, answer)
    
    if debug:
        print("\n--- CITATION DEBUG ---")
        print(f"Original unique sources count: {len(unique_sources)}")
        print(f"Citations found in text: {used_numbers}")
        print(f"Remapping: {remap}")
        print(f"Final sources count: {len(final_sources)}")
        if answer != original_answer:
            print("Normalized original answer (duplicates/spaces removed):")
            print(answer)
        print("----------------------\n")
        
    return final_answer, final_sources
