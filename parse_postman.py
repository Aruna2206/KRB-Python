import json
import os

def parse_items(items, parent_path=""):
    for item in items:
        current_name = item.get("name", "Unnamed")
        full_path = f"{parent_path}/{current_name}" if parent_path else current_name
        
        if "item" in item:
            # It's a folder
            parse_items(item["item"], full_path)
        elif "request" in item:
            # It's a request
            method = item["request"]["method"]
            url_data = item["request"]["url"]
            
            if isinstance(url_data, dict):
                raw_url = url_data.get("raw", "")
            else:
                raw_url = url_data # sometimes it's just a string

            print(f"[{method}] {full_path}")
            print(f"  URL: {raw_url}")
            print("-" * 40)

def main():
    file_path = "UCO CMS API.postman_collection.json"
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            
        print(f"Collection: {data.get('info', {}).get('name', 'Unknown')}\n")
        if "item" in data:
            parse_items(data["item"])
        else:
            print("No items found in collection.")
            
    except Exception as e:
        print(f"Error parsing JSON: {e}")

if __name__ == "__main__":
    main()
