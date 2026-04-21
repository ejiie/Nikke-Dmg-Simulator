import json
import re
from collections import Counter

# Read the json file
file_path = r'C:\Users\user\Documents\GitHub\Nikke-Dmg-Simulator\.claude\worktrees\magical-benz\Database\processed\nikke_merged_db_returned.json'
with open(file_path, 'r', encoding='utf-8') as f:
    data = json.load(f)

descriptions = []
for char_id, char_data in data['roster'].items():
    for skill in char_data['static']['skills']:
        desc = skill.get('descriptionLevel10', '')
        if desc:
            descriptions.append(desc)

# Find common patterns
print(f"Total skills: {len(descriptions)}")

# Let's extract sentences starting with "Activates" or "Affects"
activates_counter = Counter()
affects_counter = Counter()

for desc in descriptions:
    parts = desc.split('■')
    for part in parts:
        part = part.strip()
        if part.startswith('Activates'):
            match = re.match(r'Activates ([^.]*)\.', part)
            if match:
                activates_counter[match.group(1)] += 1
        if 'Affects' in part:
            match = re.search(r'Affects ([^.]*)\.', part)
            if match:
                affects_counter[match.group(1)] += 1

print("Top Triggers (Activates):", activates_counter)
print("-" * 100, end="\n\n")
print("Top Targets (Affects):", affects_counter)