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
# 1. การตั้งค่าการเชื่อมต่อฐานข้อมูล Supabase
# ==============================================================================
SUPABASE_URL = "https://ycchozbszqxxmvxwdlag.supabase.co"
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_KEY:
    raise ValueError("❌ ไม่พบ SUPABASE_KEY ใน Environment Variables")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ผังกำหนดสถานียุทธศาสตร์หลัก 10 จุด เกณฑ์เตือนภัย (ลบ.ม./วิ) และค่าสำรอง
STATIONS_CONFIG = {
    # ลุ่มน้ำเจ้าพระยา (แหล่งหลัก: HII TIWRM)
    "C2": {
        "name": "แม่น้ำเจ้าพระยา C.2 (นครสวรรค์)",
        "basin": "chao_phraya",
        "warning": 2000,
        "critical": 2800,
        "default": 1904
    },
    "C13": {
        "name": "เขื่อนเจ้าพระยา C.13 (ชัยนาท)",
        "basin": "chao_phraya",
        "warning": 2000,
        "critical": 2700,
        "default": 2200
    },
    "pasak": {
        "name": "เขื่อนป่าสักชลสิทธิ์",
        "basin": "chao_phraya",
        "warning": 400,
        "critical": 600,
        "default": 115
    },
    "rama6": {
        "name": "เขื่อนพระรามหก (แม่น้ำป่าสัก)",
        "basin": "chao_phraya",
        "warning": 500,
        "critical": 700,
        "default": 410
    },
    "C29A": {
        "name": "สถานี C.29A บางไทร (อยุธยา)",
        "basin": "chao_phraya",
        "warning": 2500,
        "critical": 3000,
        "default": 2250
    },

    # ลุ่มน้ำแม่กลอง (แหล่งหลัก: ThaiWater 5.0 และ MK Monitor)
    "srinagarind": {
        "name": "เขื่อนศรีนครินทร์ (กาญจนบุรี)",
        "basin": "mae_klong",
        "warning": 400,
        "critical": 600,
        "default": 180
    },
    "vajiralongkorn": {
        "name": "เขื่อนวชิราลงกรณ (กาญจนบุรี)",
        "basin": "mae_klong",
        "warning": 300,
        "critical": 500,
        "default": 120
    },
    "maeklong_dam": {
        "name": "เขื่อนแม่กลอง (K.10 ท่าม่วง)",
        "basin": "mae_klong",
        "warning": 1200,
        "critical": 2000,
        "default": 1000
    },

    # ลุ่มน้ำบางปะกง (แหล่งหลัก: ThaiWater 5.0)
    "khundan": {
        "name": "เขื่อนขุนด่านปราการชล",
        "basin": "bang_pakong",
        "warning": 100,
        "critical": 200,
        "default": 50
    },
    "bangpakong_gate": {
        "name": "ปตร. แม่น้ำบางปะกง",
        "basin": "bang_pakong",
        "warning": 400,
        "critical": 600,
        "default": 310
    }
}

# ==============================================================================
# 2. ดึงข้อมูลเขื่อนขนาดใหญ่จาก ThaiWater 5.0 API
# ==============================================================================
def fetch_thaiwater_dams():
    """
    ดึงข้อมูลอัตราการระบายน้ำของเขื่อน: ศรีนครินทร์, วชิราลงกรณ, ป่าสักฯ, ขุนด่านฯ
    แปลงหน่วย: ล้าน ลบ.ม./วัน -> ลบ.ม./วินาที
    """
    url = "https://twa-api-public.thaiwater.net/v2/summary/dam-summary"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
        "Origin": "https://twa.thaiwater.net",
        "Referer": "https://twa.thaiwater.net/",
        "Accept": "application/json, text/plain, */*"
    }

    dam_matches = {
        "ศรีนครินทร์": "srinagarind",
        "วชิราลงกรณ": "vajiralongkorn",
        "ป่าสัก": "pasak",
        "ขุนด่าน": "khundan"
    }

    dam_results = {}
    try:
        resp = requests.get(url, headers=headers, timeout=12)
        print(f"📡 [ThaiWater 5.0 API] HTTP Status: {resp.status_code}")

        if resp.status_code == 200:
            payload = resp.json()
            items = payload if isinstance(payload, list) else payload.get("data", [])

            for item in items:
                item_str = str(item)
                for thai_name, sid in dam_matches.items():
                    if thai_name in item_str and sid not in dam_results:
                        discharge_val = (
                            item.get("dam_discharge")
                            or item.get("discharge")
                            or item.get("outflow")
                            or item.get("dam_outflow")
                            or 0
                        )
                        try:
                            mld = float(discharge_val)
                            m3s = round((mld * 1_000_000) / 86400)
                            dam_results[sid] = m3s
                            print(f"   ✓ [Dam API] {thai_name} ({sid}): {m3s} ลบ.ม./วิ ({mld} ล้าน ลบ.ม./วัน)")
                        except ValueError:
                            pass
    except Exception as e:
        print(f"⚠️ การเชื่อมต่อ ThaiWater 5.0 API ขัดข้อง: {e}")

    return dam_results

# ==============================================================================
# 3. ดึงข้อมูลสถานีลุ่มน้ำเจ้าพระยาจาก HII TIWRM
# ==============================================================================
def scrape_hii_chaopraya():
    """
    ดึงข้อมูลอัตราไหลจริงจากผังระบายน้ำ สสน. (HII)
    ครอบคลุม: C.2 (นครสวรรค์), C.13 (ชัยนาท), C.29A (บางไทร), เขื่อนพระรามหก
    """
    url = "https://tiwrm.hii.or.th/DATA/REPORT/php/chart/chaopraya/2013/chaopraya.php"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
        "Referer": "https://tiwrm.hii.or.th/"
    }

    hii_results = {}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        print(f"📡 [HII TIWRM] HTTP Status: {resp.status_code}")

        if resp.status_code == 200:
            html = resp.content.decode("tis-620", errors="ignore")

            patterns = {
                "C2": r"C\.?\s*2[^\d]{1,80}?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)",
                "C13": r"C\.?\s*13[^\d]{1,80}?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)",
                "C29A": r"C\.?\s*29A?[^\d]{1,80}?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)",
                "rama6": r"(?:พระรามหก|S\.?\s*26)[^\d]{1,80}?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)"
            }

            for sid, pattern in patterns.items():
                match = re.search(pattern, html, re.IGNORECASE)
                if match:
                    raw_val = match.group(1).replace(",", "")
                    val = float(raw_val)
                    if val > 0:
                        hii_results[sid] = round(val)
                        print(f"   ✓ [HII Scraping] {sid}: {hii_results[sid]} ลบ.ม./วิ")
    except Exception as e:
        print(f"⚠️ การเชื่อมต่อ HII TIWRM ขัดข้อง: {e}")

    return hii_results

# ==============================================================================
# 4. ดึงข้อมูลเขื่อนแม่กลองจากระบบโทรมาตร MK Monitor (สนง.ชลประทานที่ 13)
# ==============================================================================
def scrape_maeklong_monitor():
    """
    ดึงอัตราการระบายน้ำจริงของเขื่อนแม่กลอง (K.10) จาก http://mkmonitor.ddns.net/
    """
    url = "http://mkmonitor.ddns.net/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml"
    }

    mk_results = {}
    try:
        # กำหนด timeout 10 วินาที ป้องกันเซิร์ฟเวอร์ DDNS ค้างระบบ
        resp = requests.get(url, headers=headers, timeout=10)
        print(f"📡 [MK Monitor DDNS] HTTP Status: {resp.status_code}")

        if resp.status_code == 200:
            html = resp.content.decode("tis-620", errors="ignore")
            if "เขื่อนแม่กลอง" not in html and "K.10" not in html:
                html = resp.content.decode("utf-8", errors="ignore")

            # ตรวจหาตัวเลขระบายน้ำท้ายเขื่อนแม่กลอง
            pattern = r"(?:เขื่อนแม่กลอง|K\.?\s*10)[^\d]{1,120}?([0-9]{1,3}(?:,[0-9]{3})*(?:\.[0-9]+)?)"
            match = re.search(pattern, html, re.IGNORECASE)

            if match:
                raw_val = match.group(1).replace(",", "")
                val = float(raw_val)
                if val > 0:
                    mk_results["maeklong_dam"] = round(val)
                    print(f"   ✓ [MK Monitor] เขื่อนแม่กลอง (maeklong_dam): {mk_results['maeklong_dam']} ลบ.ม./วิ")
    except Exception as e:
        print(f"⚠️ การเชื่อมต่อ mkmonitor.ddns.net ขัดข้อง: {e}")

    return mk_results

# ==============================================================================
# 5. ประมวลผลรวมและอัปเดตลง Supabase
# ==============================================================================
def sync_water_data():
    print(f"\n=======================================================")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] กำลังเริ่มกระบวนการซิงค์ข้อมูลน้ำ...")
    print(f"=======================================================")

    # ดึงข้อมูลจาก 3 แหล่ง
    dam_data = fetch_thaiwater_dams()
    hii_data = scrape_hii_chaopraya()
    mk_data = scrape_maeklong_monitor()

    now_iso = datetime.now(timezone.utc).isoformat()
    payload = []

    for sid, conf in STATIONS_CONFIG.items():
        flow_value = conf["default"]

        # จัดลำดับแหล่งข้อมูลสด
        if sid in mk_data:
            flow_value = mk_data[sid]
        elif sid in hii_data:
            flow_value = hii_data[sid]
        elif sid in dam_data:
            flow_value = dam_data[sid]

        # ประเมินเกณฑ์เตือนภัย
        if flow_value >= conf["critical"]:
            status = "critical"
        elif flow_value >= conf["warning"]:
            status = "warning"
        else:
            status = "normal"

        payload.append({
            "station_id": sid,
            "station_name": conf["name"],
            "basin": conf["basin"],
            "discharge_m3s": flow_value,
            "warning_flow": conf["warning"],
            "critical_flow": conf["critical"],
            "status": status,
            "updated_at": now_iso
        })

    try:
        res = supabase.table("water_stations").upsert(payload, on_conflict="station_id").execute()
        print(f"\n✅ ซิงค์สำเร็จสมบูรณ์! อัปเดตข้อมูลลง Supabase ทั้งหมด {len(res.data)} สถานี")
    except Exception as e:
        print(f"\n❌ ผิดพลาดในการส่งข้อมูลเข้า Supabase: {e}")

if __name__ == "__main__":
    sync_water_data()
