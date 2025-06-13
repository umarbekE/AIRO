import sqlite3
import json
import os

def export_db_to_json(db_path, output_json_path):
    try:
        # SQLite ma'lumotlar bazasiga ulanish
        conn = sqlite3.connect(db_path)
        c = conn.cursor()
        
        # Barcha ma'lumotlarni olish
        c.execute("SELECT user_id, message, response, timestamp, language FROM chat_history")
        data = c.fetchall()
        
        # JSON formatiga o'girish
        dataset = [
            {
                "user_id": row[0],
                "prompt": row[1],    # Foydalanuvchi xabari
                "response": row[2],  # Bot javobi
                "timestamp": row[3],
                "language": row[4]
            }
            for row in data
        ]
        
        # JSON fayliga yozish
        with open(output_json_path, 'w', encoding='utf-8') as f:
            json.dump(dataset, f, ensure_ascii=False, indent=2)
        
        print(f"Ma'lumotlar muvaffaqiyatli eksport qilindi: {output_json_path}")
        
    except Exception as e:
        print(f"Xato yuz berdi: {e}")
    finally:
        conn.close()

# Fayl yo'llari
db_path = "/home/cmatrix/Desktop/TG/chat_history.db"
output_json_path = "/home/cmatrix/Desktop/TG/airo_dataset.json"

# Skriptni ishga tushirish
if os.path.exists(db_path):
    export_db_to_json(db_path, output_json_path)
else:
    print(f"Ma'lumotlar bazasi topilmadi: {db_path}")