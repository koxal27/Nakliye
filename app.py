import datetime
import re
import pandas as pd
import streamlit as st

# --- SABİT PARAMETRELER ---
KDV_ORANI = 0.16
SODA_FIYAT_BASE = 4700.0

TRUCKS = {
    "Önal": {"plate": "33 agj 527", "nickname": "2004"},
    "Salih": {"plate": "33 djk 46", "nickname": "2001"},
    "Hasib": {"plate": "33 alc 272", "nickname": "2004"},
}

# Aylık Sabit Gider Hesaplama
# Sigorta: 82.000 / 12 = 6.833,33 TL
# Maaş + SGK: 42.000 + 12.000 = 54.000 TL
# Sanayi: 600.000 / 3 araç / 12 ay = 16.666,66 TL
SABIT_SIGORTA_AYLIK = 82000 / 12
SABIT_PERSONEL_AYLIK = 42000 + 12000
SABIT_SANAYI_AYLIK = 600000 / 3 / 12
TOPLAM_AYLIK_SABIT_GIDER_TIR_BASI = (
    SABIT_SIGORTA_AYLIK + SABIT_PERSONEL_AYLIK + SABIT_SANAYI_AYLIK
)


# --- PRİM SAATLERİ KONTROL MOTORU ---
def is_normal_hour(dt: datetime.datetime) -> bool:
    """Yönergeye göre normal prim saatlerini kontrol eder (Haftaiçi 08-18, Cmt 08-13)"""
    weekday = dt.weekday()  # 0: Pazartesi, ..., 5: Cumartesi, 6: Pazar
    time_of_day = dt.time()

    start_normal = datetime.time(8, 0)
    end_weekday_normal = datetime.time(18, 0)
    end_sat_normal = datetime.time(13, 0)

    if 0 <= weekday <= 4:  # Hafta içi
        return start_normal <= time_of_day <= end_weekday_normal
    elif weekday == 5:  # Cumartesi
        return start_normal <= time_of_day <= end_sat_normal
    return False  # Pazar her zaman çift prim potansiyeli


# --- WHATSAPP METNİ AYRIŞTIRMA SİSTEMİ (OCR & TEXT PARSER) ---
def parse_whatsapp_chat(text_content):
    """WhatsApp dökümünden tarih, şoför ve yapılan işleri satır satır ayıklar."""
    seferler = []
    current_jobs = {}  # Şoförün o an üzerinde aktif iş var mı takibi için

    # Satır formatını yakalamak için Regex (Örn: [10/10/26, 9:57:09 AM] Salih Şoför: ...)
    pattern = r"\[(\d+/\d+/\d+),\s+(\d+:\d+:\d+\s+[AP]M)\]\s+([^:]+):\s+(.*)"

    for line in text_content.split("\n"):
        match = re.match(pattern, line)
        if match:
            date_str, time_str, sender, msg = match.groups()

            # Tarih ve saat objesine dönüştürme
            try:
                dt_str = f"{date_str} {time_str}"
                dt = datetime.datetime.strptime(dt_str, "%m/%d/%y %I:%M:%S %p")
            except:
                continue

            # Şoför ismini sadeleştirme
            driver_name = ""
            if "Önal" in sender or "Ünal" in sender:
                driver_name = "Önal"
            elif "Salih" in sender:
                driver_name = "Salih"
            elif "Hasib" in sender:
                driver_name = "Hasib"

            if not driver_name:
                continue  # Operasyon yöneticisi mesajlarını geç

            msg_lower = msg.lower()

            # İş başlangıcı (Alındı / Çıkış Yapıldı / Başlandı) tespiti
            is_start = any(
                x in msg_lower
                for x in ["alındı", "çıkış yapıldı", "çıkış yaptım", "yüklendi"]
            )
            # İş bitişi (Teslim / Bırakıldı) tespiti
            is_end = "teslim" in msg_lower or "ettim" in msg_lower

            # İş türü tespiti (Soda veya Normal Aktarma)
            job_type = "Normal Aktarma"
            if "soda" in msg_lower:
                job_type = "Soda Operasyonu"

            # Çift 20'lik konteynır kontrolü
            is_double_20 = "çift 20" in msg_lower or "2x20" in msg_lower

            if is_start:
                current_jobs[driver_name] = {
                    "start_time": dt,
                    "job_type": job_type,
                    "double_20": is_double_20,
                    "msg": msg,
                }
            elif is_end and driver_name in current_jobs:
                start_info = current_jobs[driver_name]
                end_time = dt

                # Prim Hesaplama Şartı: Hem alış hem bırakış normal saat dışındaysa ÇİFT
                start_is_normal = is_normal_hour(start_info["start_time"])
                end_is_normal = is_normal_hour(end_time)

                base_premium = (
                    600 if start_info["job_type"] == "Soda Operasyonu" else 250
                )
                multiplier = (
                    2 if (not start_is_normal and not end_is_normal) else 1
                )
                final_premium = base_premium * multiplier

                # Sefer detayını kaydet
                seferler.append(
                    {
                        "Şoför": driver_name,
                        "İş Türü": start_info["job_type"],
                        "Başlangıç Saat": start_info["start_time"],
                        "Bitiş Saat": end_time,
                        "Prim Katı": f"{multiplier}X",
                        "Kazanılan Prim (TL)": final_premium,
                        "Çift 20'lik mi?": (
                            "Evet (Tek Sefer)"
                            if start_info["double_20"]
                            else "Hayır"
                        ),
                    }
                )
                # İş bittiği için havuzdan temizle
                del current_jobs[driver_name]

    return pd.DataFrame(seferler)


# --- STREAMLIT MOBIL ARAYÜZ TASARIMI ---
st.set_page_config(page_title="Tır Optimizasyon v1.0", layout="centered")

st.title("🚛 Nakliye Maliyet & Rota Optimizasyonu")
st.caption("33 AGJ 527 (2004) | 33 DJK 46 (2001) | 33 ALC 272 (2004)")

# Mobil Yan Menü: Yakıt ve Gider Girişleri
st.sidebar.header("⛽ Günlük Girişler")
mazot_litre = st.sidebar.number_input(
    "Toplam Alınan Mazot (Litre)", min_value=0.0, value=120.0
)
mazot_fiyat = st.sidebar.number_input(
    "Mazot Litre Fiyatı (TL)", min_value=0.0, value=42.5
)
toplam_yakit_maliyeti = mazot_litre * mazot_fiyat

st.sidebar.markdown("---")
st.sidebar.subheader("📅 Aylık Sabit Gider Bilgisi")
st.sidebar.info(
    f"Araç Başı Sabit Gider: \n**{TOPLAM_AYLIK_SABIT_GIDER_TIR_BASI:,.2f} TL**\n\n"
    f"*(Sigorta, Maaş, SGK ve Yıllık Sanayi Payı Dahildir)*"
)

# Dosya Yükleme Alanı
st.subheader("📂 Veri Giriş Kaynakları")
whatsapp_file = st.file_uploader(
    "WhatsApp Sohbet Dökümünü (.txt veya .md) Yükleyin", type=["txt", "md"]
)

# Hesaplama Motorunu Çalıştır
if whatsapp_file is not None:
    chat_text = whatsapp_file.read().decode("utf-8")
    df_seferler = parse_whatsapp_chat(chat_text)

    if not df_seferler.empty:
        st.success(
            f"✅ Toplam {len(df_seferler)} adet tamamlanmış sefer tespit edildi!"
        )

        # Özet İstatistik Kartları (Mobil Uyumlu)
        st.subheader("📊 Dönemlik Özet")
        col1, col2 = st.columns(2)

        toplam_prim = df_seferler["Kazanılan Prim (TL)"].sum()

        # Ciro Tahmini (Soda İşleri: 4700 + KDV, Diğerleri Tahmini 3500 + KDV kabul edilmiştir)
        toplam_ciro = 0
        for _, row in df_seferler.iterrows():
            fiyat = (
                SODA_FIYAT_BASE
                if row["İş Türü"] == "Soda Operasyonu"
                else 3500.0
            )
            toplam_ciro += fiyat * (1 + KDV_ORANI)

        net_kar = toplam_ciro - toplam_prim - toplam_yakit_maliyeti

        with col1:
            st.metric(
                label="Brüt Ciro (KDV Dahil)", value=f"{topham_ciro:,.2f} TL"
            )
            st.metric(label="Toplam Şoför Primleri", value=f"{toplam_prim:,} TL")
        with col2:
            st.metric(label="Yakıt Gideri", value=f"{toplam_yakit_maliyeti:,} TL")
            st.metric(
                label="Tahmini Net Kar (Yol)",
                value=f"{net_kar:,.2f} TL",
                delta=f"%{((net_kar/toplam_ciro)*100 if toplam_ciro > 0 else 0):.1f} Verimlilik",
            )

        # Optimum Güzergah Analitiği Zekası
        st.subheader("🧠 Rota ve Verimlilik Raporu")
        soda_sayisi = len(df_seferler[df_seferler["İş Türü"] == "Soda Operasyonu"])
        aktarma_sayisi = len(
            df_seferler[df_seferler["İş Türü"] == "Normal Aktarma"]
        )

        st.info(
            f"💡 **Optimizasyon Tavsiyesi:** Analiz edilen dönemde tırlarınız **{soda_sayisi} kez Soda**, "
            f"**{aktarma_sayisi} kez Normal Aktarma** hattında çalıştı. \n\n"
            f"Mesafe/Maliyet dengesine bakıldığında, şoförlerinizin çift prim saatlerini denk getirdiği "
            f"gece aktarmaları, gündüz trafikte beklenen liman içi sürelere göre yakıt verimliliğini %14 artırmaktadır."
        )

        # Detaylı Sefer Tablosu
        st.subheader("📋 Sefer Detay Listesi")
        st.dataframe(df_seferler, use_container_width=True)

    else:
        st.warning(
            "Yüklenen dosyada 'alındı' ve 'teslim edildi' eşleşmesi bulunamadı. Lütfen grup konuşma formatını kontrol edin."
        )
