import os
import sys
import re
import requests
from datetime import datetime, timezone
from supabase import create_client, Client

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# ==============================================================================
# เชื่อมต่อ Supabase
# ==============================================================================
SUPABASE_URL = "https://ycchozbszqxxmvxwdlag.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_KEY:
    raise ValueError("ไม่พบ SUPABASE_KEY ใน Environment Variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# โครงสร้าง 10 สถานีหลักและค่ามาตรฐานสำรอง (Fallback)
STATIONS = {
    "C2": {"name": "แม่น้ำเจ้าพระยา C.2 (นครสวรรค์)", "basin": "chao_phraya", "warning": 2000, "critical": 2800, "default": 1904},
    "C13": {"name": "เขื่อนเจ้าพระยา C.13 (ชัยนาท)", "basin": "chao_phraya", "warning": 2000, "critical": 2700, "default": 2200},
    "C29A": {"name": "สถานี C.29A บางไทร (อยุธยา)", "basin": "chao_phraya", "warning": 2500, "critical": 3000, "default": 2250},
    "rama6": {"name": "เขื่อนพระรามหก (แม่น้ำป่าสัก)", "basin": "chao_phraya", "warning": 500, "critical": 700, "default": 410},
    "pasak": {"name": "เขื่อนป่าสักชลสิทธิ์", "basin": "chao_phraya", "warning": 400, "critical": 600, "default": 115},
    "srinagarind": {"name": "เขื่อนศรีนครินทร์", "basin": "mae_klong", "warning": 400, "critical": 600, "default": 180},
    "maeklong_dam": {"name": "เขื่อนแม่กลอง (K.10)", "basin": "mae_klong", "warning": 1200, "critical": 2000, "default": 1000},
    "khundan": {"name": "เขื่อนขุนด่านปราการชล", "basin": "bang_pakong", "warning": 100, "critical": 200, "default": 50},
    "bangpakong_gate": {"name": "ปตร. แม่น้ำบางปะกง", "basin": "bang_pakong", "warning": 400, "critical": 600, "default": 310},
    "tha_chin": {"name": "ผันน้ำท่าจีน (พลเทพ)", "basin": "chao_phraya", "warning": 350, "critical": 500, "default": 310}
}

def scrape_rid_hydro1():
    """
    ดึงข้อมูลอัตราการไหลจริง (m3/s) รายชั่วโมงจากระบบโทรมาตร กรมชลประทาน (RID Hydro-1)
    ครอบคลุม C.2, C.13, C.29A และเขื่อนพระรามหก (S.26)
    """
    url = "http://www.hydro-1.net/Data/HD-06/hourly/all_hourly.php"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
    }

    scraped_data = {}
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        resp.encoding = "tis-620"  # ฟอนต์มาตรฐานระบบโทรมาตรชลประทาน
        html = resp.text

        # รูปแบบตาราง HTML: ค้นหาแถวของสถานี แล้วดึงคอลัมน์ Discharge (ลบ.ม./วินาที)
        patterns = {
            "C2": r"C\.2[^\d]*?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)",
            "C13": r"C\.13[^\d]*?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)",
            "C29A": r"C\.29A[^\d]*?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)",
            "rama6": r"(?:S\.26|พระรามหก)[^\d]*?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)"
        }

        for st_id, pattern in patterns.items():
            match = re.search(pattern, html, re.IGNORECASE)
            if match:
                clean_num = match.group(1).replace(",", "")
                val = float(clean_num)
                # กรองค่าขยะ/เซนเซอร์เสีย (เช่น -999 หรือ 0 ในฤดูน้ำ)
                if val > 0:
                    scraped_data[st_id] = round(val)
                    print(f"📡 [RID Live] {st_id}: {scraped_data[st_id]} ลบ.ม./วิ")
    except Exception as e:
        print(f"⚠️ ดึงข้อมูลจาก RID Hydro-1 ขัดข้อง: {e}")

    return scraped_data

def scrape_egat_dams():
    """
    ดึงข้อมูลการระบายน้ำของเขื่อนขนาดใหญ่ (กฟผ. และกรมชลฯ)
    """
    url = "https://api-v3.thaiwater.net/v2/analyst/water/dam"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": "https://www.thaiwater.net/"
    }

    dam_discharge = {}
    dam_map = {
        9: "srinagarind",      # เขื่อนศรีนครินทร์
        16: "pasak",            # เขื่อนป่าสักชลสิทธิ์
        20: "khundan"           # เขื่อนขุนด่านปราการชล
    }

    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            dams = resp.json().get("data", {}).get("dam_daily", [])
            for d in dams:
                dam_id = d.get("dam_id")
                if dam_id in dam_map:
                    # แปลงหน่วย ล้าน ลบ.ม./วัน -> ลบ.ม./วินาที
                    mld = float(d.get("dam_discharge", 0) or 0)
                    m3s = round((mld * 1_000_000) / 86400)
                    dam_discharge[dam_map[dam_id]] = m3s
                    print(f"📡 [Dam Live] {dam_map[dam_id]}: {m3s} ลบ.ม./วิ")
    except Exception as e:
        print(f"⚠️ ดึงข้อมูลเขื่อนขัดข้อง: {e}")

    return dam_discharge

def run_sync():
    print(f"\n=======================================================")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] เริ่มกระบวนการซิงค์ข้อมูลน้ำจริง...")
    print(f"=======================================================")

    # 1. กวาดข้อมูลสด
    rid_flows = scrape_rid_hydro1()
    dam_flows = scrape_egat_dams()

    # 2. ผสานข้อมูลทั้ง 10 จุด
    now_iso = datetime.now(timezone.utc).isoformat()
    records = []

    for sid, conf in STATIONS.items():
        flow_value = conf["default"]

        # จัดลำดับความสำคัญของข้อมูลสด
        if sid in rid_flows:
            flow_value = rid_flows[sid]
        elif sid in dam_flows:
            flow_value = dam_flows[sid]

        # ประเมินระดับการเตือนภัย
        if flow_value >= conf["critical"]:
            status = "critical"
        elif flow_value >= conf["warning"]:
            status = "warning"
        else:
            status = "normal"

        records.append({
            "station_id": sid,
            "station_name": conf["name"],
            "basin": conf["basin"],
            "discharge_m3s": flow_value,
            "warning_flow": conf["warning"],
            "critical_flow": conf["critical"],
            "status": status,
            "updated_at": now_iso
        })

    # 3. อัปเดตทับลง Supabase
    try:
        res = supabase.table("water_stations").upsert(records, on_conflict="station_id").execute()
        print(f"\n✅ ซิงค์สำเร็จสมบูรณ์! อัปเดตลงตาราง Supabase เรียบร้อย {len(res.data)} สถานี")
    except Exception as e:
        print(f"\n❌ ผิดพลาดในการบันทึกข้อมูลเข้า Supabase: {e}")

if __name__ == "__main__":
    run_sync()
