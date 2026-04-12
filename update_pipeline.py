import requests
import json
import base64
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TOKEN = os.getenv("GITHUB_TOKEN")
REPO = os.getenv("GITHUB_REPO")
FILE_PATH = "pipeline_status.json"
API_URL = f"https://api.github.com/repos/{REPO}/contents/{FILE_PATH}"

HEADERS = {
    "Authorization": f"token {TOKEN}",
    "Accept": "application/vnd.github.v3+json"
}

def get_current_status():
    """GitHub에서 현재 상태 가져오기"""
    res = requests.get(API_URL, headers=HEADERS)
    if res.status_code != 200:
        raise ValueError(f"GitHub API 오류: {res.status_code} - {res.text}")
    data = res.json()
    if "content" not in data:
        raise KeyError(f"'content' 키 없음. 응답: {data}")
    content = base64.b64decode(data["content"]).decode("utf-8")
    return json.loads(content), data["sha"]

def update_status(item_key: str, new_status: str):
    """
    특정 항목 상태 업데이트
    status: done / todo / soon / mid / later
    """
    status_data, sha = get_current_status()
    
    if item_key not in status_data["items"]:
        print(f"항목 없음: {item_key}")
        print("사용 가능한 항목:", list(status_data["items"].keys()))
        return
    
    old_status = status_data["items"][item_key]["status"]
    status_data["items"][item_key]["status"] = new_status
    status_data["updated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    content = base64.b64encode(
        json.dumps(status_data, ensure_ascii=False, indent=2).encode("utf-8")
    ).decode("utf-8")
    
    payload = {
        "message": f"update: {item_key} → {new_status}",
        "content": content,
        "sha": sha
    }
    
    res = requests.put(API_URL, headers=HEADERS, json=payload)
    if res.status_code == 200:
        print(f"업데이트 완료: {item_key} [{old_status} → {new_status}]")
        print(f"반영 URL: https://leokong-c.github.io/Jjlaylist_Pipeline/jjlaylist_pipeline.html")
    else:
        print(f"오류: {res.status_code} - {res.text}")


def show_status():
    """현재 전체 상태 출력"""
    status_data, _ = get_current_status()
    print(f"\n업데이트: {status_data['updated_at']}\n")
    for key, item in status_data["items"].items():
        icon = {"done":"✅", "todo":"⬜", "soon":"🟡", "mid":"🟠", "later":"🔴"}.get(item["status"], "❓")
        print(f"{icon} [{key}] {item['label']}")


if __name__ == "__main__":
    import sys
    
    if len(sys.argv) == 1:
        show_status()
    elif len(sys.argv) == 3:
        update_status(sys.argv[1], sys.argv[2])
    else:
        print("사용법:")
        print("  python update_pipeline.py              # 전체 상태 보기")
        print("  python update_pipeline.py [항목] [상태] # 상태 업데이트")
        print("\n예시:")
        print("  python update_pipeline.py shorts done")
        print("  python update_pipeline.py trailer done")