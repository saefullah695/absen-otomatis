"""
Sync Time Management SAT -> Google Spreadsheet
Jadwal: setiap hari jam 01:00 WIB
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

        # ---------- 4. Tarik data API Time Management ----------
        log("4. Menarik data API Time Management...")
        periode = datetime.now(WIB).strftime("01-%m-%Y")  # pakai WIB

        url_api = "https://hctm0201.sat.co.id/input_shift/pick/data"
        params = {
            'limit': 100,
            'offset': 0,
            'search_filter': '',
            'periode': periode,
            'lokasi': 'A',
            'kode_branch': 'KZ01',
        }

        # sinkronisasi cookie/domain
        session.get("https://hctm0201.sat.co.id/input_shift")
        res_data = session.get(url_api, params=params, timeout=60)

        if res_data.status_code != 200:
            log(f"❌ Gagal tarik data. Status: {res_data.status_code}")
            log(f"   Body: {res_data.text[:300]}")
            return

        json_data = res_data.json()
        log(f"✅ Data ditarik. Periode: {periode}")

        # ---------- 5. Kirim ke Google Spreadsheet ----------
        log("5. Mengirim data ke Google Spreadsheet...")
        try:
            res_gas = requests.post(
                GAS_WEB_APP_URL, json=json_data, timeout=120
            )
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
#  SCHEDULER — SETIAP HARI 01:00 WIB
# ==========================================================
if __name__ == "__main__":
    log("=" * 60)
    log(f"Timezone       : {datetime.now(WIB).strftime('%Z %z')}")
    log(f"Waktu sekarang : {datetime.now(WIB).strftime('%Y-%m-%d %H:%M:%S')}")
    log(f"NIK            : {NIK[:4]}****")
    log("=" * 60)

    # (Opsional) Jalankan sekali saat worker start:
    # run_sync()

    schedule.every().day.at("01:00").do(run_sync)
    log("⏰ Scheduler aktif: setiap hari jam 01:00 WIB")
    log("   Worker berjalan. Tekan Ctrl+C untuk stop (di lokal).\n")

    while True:
        try:
            schedule.run_pending()
        except KeyboardInterrupt:
            log("👋 Scheduler dihentikan.")
            break
        except Exception as e:
            log(f"❌ Error di loop scheduler: {e}")
        time.sleep(30)
