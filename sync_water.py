import os
import sys
from datetime import datetime, timezone
from supabase import create_client, Client

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ==============================================================================
# ดึงค่าจาก GitHub Secrets (เมื่อรันบนคลาวด์)
# หากรันในเครื่องตัวเอง จะดึงค่า fallback ด้านหลังมาใช้งาน
# ==============================================================================
SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://ycchozbszqxxmvxwdlag.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

# กรณีทดสอบรันในเครื่อง (Local) ถ้าไม่มีตัวแปรระบบ ให้ใช้ค่าสำรอง
if not SUPABASE_KEY:
    SUPABASE_KEY = "ไม่พบคีย์ SUPABASE_KEY ใน Environment Variables"

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def sync_data():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] กำลังเตรียมส่งข้อมูลเข้า Supabase...")

    # ข้อมูลสถานการณ์น้ำ 10 จุดยุทธศาสตร์
    stations_data = [
        {"station_id": "srinagarind", "station_name": "เขื่อนศรีนครินทร์ (กาญจนบุรี)", "basin": "mae_klong", "discharge_m3s": 180, "warning_flow": 800, "critical_flow": 1200, "water_level_msl": None},
        {"station_id": "maeklong_dam", "station_name": "เขื่อนแม่กลอง (K.10)", "basin": "mae_klong", "discharge_m3s": 3000, "warning_flow": 1200, "critical_flow": 2000, "water_level_msl": None},
        {"station_id": "C2", "station_name": "แม่น้ำเจ้าพระยา สถานี C.2", "basin": "chao_phraya", "discharge_m3s": 1904, "warning_flow": 2000, "critical_flow": 2800, "water_level_msl": 23.45},
        {"station_id": "C13", "station_name": "เขื่อนเจ้าพระยา (ชัยนาท)", "basin": "chao_phraya", "discharge_m3s": 2200, "warning_flow": 1800, "critical_flow": 2000, "water_level_msl": 16.20},
        {"station_id": "pasak", "station_name": "เขื่อนป่าสักชลสิทธิ์", "basin": "chao_phraya", "discharge_m3s": 115, "warning_flow": 400, "critical_flow": 600, "water_level_msl": 38.50},
        {"station_id": "rama6", "station_name": "เขื่อนพระรามหก", "basin": "chao_phraya", "discharge_m3s": 410, "warning_flow": 500, "critical_flow": 700, "water_level_msl": None},
        {"station_id": "C29A", "station_name": "สถานี C.29A บางไทร", "basin": "chao_phraya", "discharge_m3s": 2250, "warning_flow": 2200, "critical_flow": 2800, "water_level_msl": 3.10},
        {"station_id": "khundan", "station_name": "เขื่อนขุนด่านปราการชล", "basin": "bang_pakong", "discharge_m3s": 50, "warning_flow": 150, "critical_flow": 250, "water_level_msl": None},
        {"station_id": "kgt3", "station_name": "สถานี KGT.3 กบินทร์บุรี", "basin": "bang_pakong", "discharge_m3s": 340, "warning_flow": 450, "critical_flow": 578, "water_level_msl": 8.90},
        {"station_id": "bangpakong_gate", "station_name": "ปตร. แม่น้ำบางปะกง", "basin": "bang_pakong", "discharge_m3s": 310, "warning_flow": 400, "critical_flow": 600, "water_level_msl": None}
    ]

    now_iso = datetime.now(timezone.utc).isoformat()
    for item in stations_data:
        flow = item["discharge_m3s"]
        if flow >= item["critical_flow"]:
            item["status"] = "critical"
        elif flow >= item["warning_flow"]:
            item["status"] = "warning"
        else:
            item["status"] = "normal"
        item["updated_at"] = now_iso

    try:
        res = supabase.table("water_stations").upsert(stations_data, on_conflict="station_id").execute()
        print(f"✅ บันทึกข้อมูลสำเร็จเรียบร้อย! อัปเดตทั้งหมด {len(res.data)} สถานี")
    except Exception as e:
        print("❌ เกิดข้อผิดพลาด:", e)

if __name__ == "__main__":
    sync_data()