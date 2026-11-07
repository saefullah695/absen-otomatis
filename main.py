"""
Sync Time Management SAT -> Google Spreadsheet
Jadwal: setiap 3 jam sekali WIB (00,03,06,09,12,15,18,21)
Deploy: ZevCloud Worker
"""

import os
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests
import pyotp
import schedule


# ==========================================================
#  KONFIGURASI (dari Environment Variables)
# ==========================================================
NIK              = os.environ["NIK"]
PIN              = os.environ["PIN"]
SECRET_TOTP      = os.environ["SECRET_TOTP"]
GAS_WEB_APP_URL  = os.environ["GAS_WEB_APP_URL"]

WIB = ZoneInfo("Asia/Jakarta")

# Jam eksekusi: setiap 3 jam, aligned ke jam bulat WIB
JADWAL_JAM = ["00:00", "03:00", "06:00", "09:00",
              "12:00", "15:00", "18:00", "21:00"]

PAGE_LIMIT = 100

HEADERS = {
    'User-Agent': (
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
        'AppleWebKit/537.36 (KHTML, like Gecko) '
        'Chrome/156.0.0.0 Safari/537.36'
    ),
    'Accept': (
        'text/html,application/xhtml+xml,application/xml;q=0.9,'
        'image/avif,image/webp,image/apng,*/*;q=0.8'
    ),
    'Accept-Language': 'id-ID,id;q=0.9,en-US;q=0.8,en;q=0.7',
}


def log(msg: str):
    """Print dengan timestamp WIB."""
    print(f"[{datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')} WIB] {msg}", flush=True)


# ==========================================================
#  FUNGSI UTAMA
# ==========================================================
def run_sync():
    session = requests.Session()
    session.headers.update(HEADERS)

    try:
        # ---------- 1. Ambil tiket SSO ----------
        log("1. Mengambil tiket SSO...")
        res_intranet = session.get("https://intranet.sat.co.id", allow_redirects=True)
        login_post_url = res_intranet.url.replace("/?data=", "/login?data=")

        # ---------- 2. Generate OTP ----------
        otp_code = pyotp.TOTP(SECRET_TOTP).now()
        log(f"2. Generate OTP: {otp_code}")

        # ---------- 3. Login SSO ----------
        log("3. Login SSO...")
        payload = {"nik": NIK, "pin": PIN, "otp": otp_code}
        post_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Origin": "https://asl.sat.co.id",
            "Referer": res_intranet.url,
        }
        res_login = session.post(
            login_post_url, data=payload, headers=post_headers, allow_redirects=True
        )

        if "login" in res_login.url.lower():
            log("❌ Login Gagal.")
            return

        log("✅ Login Berhasil! Cookie didapat.")

        # ---------- 4. Tarik data API Time Management (PAGINATION) ----------
        log("4. Menarik data API Time Management...")
        periode = datetime.now(WIB).strftime("01-%m-%Y")

        url_api = "https://hctm0201.sat.co.id/input_shift/pick/data"
        session.get("https://hctm0201.sat.co.id/input_shift")

        all_rows = []
        offset = 0
        while True:
            params = {
                'limit': PAGE_LIMIT,
                'offset': offset,
                'search_filter': '',
                'periode': periode,
                'lokasi': 'A',
                'kode_branch': 'KZ01',
            }
            res_data = session.get(url_api, params=params, timeout=60)

            if res_data.status_code != 200:
                log(f"❌ Gagal tarik data. Status: {res_data.status_code}")
                log(f"   Body: {res_data.text[:300]}")
                return

            json_page = res_data.json()
            rows = (json_page.get('data') or {}).get('data_karyawan') or []
            all_rows.extend(rows)
            log(f"   Halaman offset={offset} → {len(rows)} baris (total {len(all_rows)})")

            if len(rows) < PAGE_LIMIT:
                break
            offset += PAGE_LIMIT

        if not all_rows:
            log("⚠️ Tidak ada data karyawan. Skip kirim.")
            return

        # Gabungkan ke struktur asli
        json_data = json_page  # struktur terakhir (metadata periode dsb)
        json_data.setdefault('data', {})
        json_data['data']['data_karyawan'] = all_rows

        log(f"✅ Data ditarik total {len(all_rows)} baris. Periode: {periode}")

        # Log sample key tanggal untuk verifikasi format
        sample_keys = [k for k in all_rows[0].keys()
                       if isinstance(k, str) and len(k) == 10 and '-' in k][:3]
        log(f"   Sample key tanggal dari API: {sample_keys}")

        # ---------- 5. Kirim ke Google Spreadsheet ----------
        log("5. Mengirim data ke Google Spreadsheet...")
        try:
            res_gas = requests.post(GAS_WEB_APP_URL, json=json_data, timeout=180)
            if res_gas.status_code == 200:
                log(f"🎉 SUKSES! Respon: {res_gas.text[:300]}")
            else:
                log(f"❌ Gagal kirim ke Google. Status: {res_gas.status_code}")
                log(f"   Body: {res_gas.text[:300]}")
        except Exception as e:
            log(f"❌ Error saat kirim ke Google: {e}")

    except Exception as e:
        log(f"❌ Error tak terduga di run_sync(): {e}")


# ==========================================================
#  SCHEDULER — SETIAP 3 JAM (aligned ke jam bulat WIB)
# ==========================================================
if __name__ == "__main__":
    log("=" * 60)
    log(f"Timezone       : {datetime.now(WIB).strftime('%Z %z')}")
    log(f"Waktu sekarang : {datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"NIK            : {NIK[:4]}****")
    log("=" * 60)

    # (Opsional) jalankan sekali saat worker start:
    # run_sync()

    for jam in JADWAL_JAM:
        schedule.every().day.at(jam).do(run_sync)

    log(f"⏰ Scheduler aktif: setiap 3 jam → {', '.join(JADWAL_JAM)} WIB")
    log("   Worker berjalan. Tekan Ctrl+C untuk stop (di lokal).\n")

    while True:
        try:
            schedule.run_pending()
            time.sleep(20)
        except KeyboardInterrupt:
            log("👋 Scheduler dihentikan.")
            break
        except Exception as e:
            log(f"❌ Error di loop scheduler: {e}")
            time.sleep(30)
