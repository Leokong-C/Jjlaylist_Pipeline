import re

f = open('J_Jlaylist_50songs_MoonlitMusicalFeline_full_lyrics_suno_thumbnail_bundle.md', encoding='utf-8')
content = f.read()
f.close()

out = open('suno_prompts_extracted.txt', 'w', encoding='utf-8')
songs = re.split(r'## \d+\.', content)

for i, song in enumerate(songs[1:], 1):
    lines = song.strip().split('\n')
    title = lines[0].strip()
    prompt_start = song.find('```text')
    prompt_end = song.find('```', prompt_start + 7)
    if prompt_start != -1:
        prompt = song[prompt_start + 7:prompt_end].strip()
        out.write(f'=== {i:02d}. {title} ===\n{prompt}\n\n')

out.close()
print(f'완료! suno_prompts_extracted.txt 생성됨')