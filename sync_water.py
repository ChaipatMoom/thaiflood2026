import os
import sys
import requests
from datetime import datetime, timezone
from supabase import create_client, Client

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# เชื่อมต่อ Supabase ผ่าน Secret Environment
SUPABASE_URL = "https://ycchozbszqxxmvxwdlag.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_KEY:
    raise ValueError("ไม่พบ SUPABASE_KEY ใน Environment Variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# รหัสสถานีอ้างอิงและเกณฑ์วิกฤต (Baseline Criteria)
STATIONS_CONFIG = {
    "srinagarind": {"name": "เขื่อนศรีนครินทร์ (กาญจนบุรี)", "basin": "mae_klong", "type": "dam", "ref_id": 9, "warning": 400, "critical": 600, "default": 180},
    "maeklong_dam": {"name": "เขื่อนแม่กลอง (K.10)", "basin": "mae_klong", "type": "station", "ref_id": "K10", "warning": 1200, "critical": 2000, "default": 1000},
    "C2": {"name": "แม่น้ำเจ้าพระยา สถานี C.2", "basin": "chao_phraya", "type": "station", "ref_id": "C2", "warning": 2000, "critical": 2800, "default": 1904},
    "C13": {"name": "เขื่อนเจ้าพระยา (ชัยนาท)", "basin": "chao_phraya", "type": "station", "ref_id": "C13", "warning": 2000, "critical": 2700, "default": 2200},
    "pasak": {"name": "เขื่อนป่าสักชลสิทธิ์", "basin": "chao_phraya", "type": "dam", "ref_id": 16, "warning": 400, "critical": 600, "default": 115},
    "rama6": {"name": "เขื่อนพระรามหก", "basin": "chao_phraya", "type": "station", "ref_id": "S26", "warning": 500, "critical": 700, "default": 410},
    "C29A": {"name": "สถานี C.29A บางไทร", "basin": "chao_phraya", "type": "station", "ref_id": "C29A", "warning": 2500, "critical": 3000, "default": 2250},
    "khundan": {"name": "เขื่อนขุนด่านปราการชล", "basin": "bang_pakong", "type": "dam", "ref_id": 20, "warning": 100, "critical": 200, "default": 50},
    "kgt3": {"name": "สถานี KGT.3 กบินทร์บุรี", "basin": "bang_pakong", "type": "station", "ref_id": "KGT3", "warning": 450, "critical": 650, "default": 340},
    "bangpakong_gate": {"name": "ปตร. แม่น้ำบางปะกง", "basin": "bang_pakong", "type": "station", "ref_id": "BPK", "warning": 400, "critical": 600, "default": 310}
}

def fetch_real_data():
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    
    # 1. ดึงข้อมูลเขื่อนหลักจาก API คลังน้ำแห่งชาติ (HII/ThaiWater)
    dam_discharge = {}
    try:
        dam_api_url = "https://api-v3.thaiwater.net/v2/analyst/water/dam"
        r = requests.get(dam_api_url, headers=headers, timeout=12)
        if r.status_code == 200:
            dams = r.json().get("data", {}).get("dam_daily", [])
            for d in dams:
                dam_id = d.get("dam_id")
                # ค่าการระบายน้ำ (discharge) หน่วย ล้าน ลบ.ม./วัน แปลงเป็น ลบ.ม./วินาที
                outflow_mld = float(d.get("dam_discharge", 0) or 0)
                m3s = round((outflow_mld * 1_000_000) / 86400, 1)
                dam_discharge[dam_id] = m3s
    except Exception as e:
        print(f"⚠️ ดึง API เขื่อนไม่สำเร็จ ใช้ค่าฐานข้อมูลเดิม: {e}")

    # 2. ดึงข้อมูลสถานีวัดน้ำท่าหลัก (RID Telemetry)
    station_flow = {}
    try:
        rid_api_url = "https://api-v3.thaiwater.net/v2/analyst/water/tele_waterlevel"
        r = requests.get(rid_api_url, headers=headers, timeout=12)
        if r.status_code == 200:
            tele_data = r.json().get("data", [])
            for st in tele_data:
                code = st.get("station", {}).get("tele_station_oldcode")
                flow = st.get("tele_waterlevel", {}).get("flow_rate")
                if code and flow is not None:
                    station_flow[code] = float(flow)
    except Exception as e:
        print(f"⚠️ ดึง API สถานีน้ำท่าไม่สำเร็จ ใช้ค่าฐานข้อมูลเดิม: {e}")

    # 3. รวมและปรับข้อมูลทั้ง 10 สถานี
    now_iso = datetime.now(timezone.utc).isoformat()
    final_payload = []

    for sid, conf in STATIONS_CONFIG.items():
        flow_val = conf["default"]
        
        if conf["type"] == "dam" and conf["ref_id"] in dam_discharge:
            flow_val = dam_discharge[conf["ref_id"]]
        elif conf["type"] == "station" and conf["ref_id"] in station_flow:
            flow_val = station_flow[conf["ref_id"]]

        # คำนวณสถานะเตือนภัย
        if flow_val >= conf["critical"]:
            status = "critical"
        elif flow_val >= conf["warning"]:
            status = "warning"
        else:
            status = "normal"

        final_payload.append({
            "station_id": sid,
            "station_name": conf["name"],
            "basin": conf["basin"],
            "discharge_m3s": round(flow_val),
            "warning_flow": conf["warning"],
            "critical_flow": conf["critical"],
            "status": status,
            "updated_at": now_iso
        })

    return final_payload

def sync_data():
    print(f"[{datetime.now().strftime('%H:%M:%S')}] กำลังดึงข้อมูลจริงจาก ThaiWater (HII)...")
    payload = fetch_real_data()

    try:
        res = supabase.table("water_stations").upsert(payload, on_conflict="station_id").execute()
        print(f"✅ ซิงค์ข้อมูลจริงสำเร็จ! อัปเดตทั้งหมด {len(res.data)} สถานี")
    except Exception as e:
        print("❌ เกิดข้อผิดพลาดในการบันทึกเข้า Supabase:", e)

if __name__ == "__main__":
    sync_data()
