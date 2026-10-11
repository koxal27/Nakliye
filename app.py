import datetime
import re
import pandas as pd
import streamlit as st

# --- SABİT PARAMETRELER ---
KDV_ORANI = 0.16
SODA_FIYAT_BASE = 4700.0

SABIT_SIGORTA_AYLIK = 82000 / 12
SABIT_PERSONEL_AYLIK = 42000 + 12000
SABIT_SANAYI_AYLIK = 600000 / 3 / 12
TOPLAM_AYLIK_SABIT_GIDER_TIR_BASI = (
    SABIT_SIGORTA_AYLIK + SABIT_PERSONEL_AYLIK + SABIT_SANAYI_AYLIK
)


def is_normal_hour(dt: datetime.datetime) -> bool:
    """Yönergeye göre normal prim saatlerini kontrol eder (Haftaiçi 08-18, Cmt 08-13)"""
    weekday = dt.weekday()
    time_of_day = dt.time()

    start_normal = datetime.time(8, 0)
    end_weekday_normal = datetime.time(18, 0)
    end_sat_normal = datetime.time(13, 0)

    if 0 <= weekday <= 4:
        return start_normal <= time_of_day <= end_weekday_normal
    elif weekday == 5:
        return start_normal <= time_of_day <= end_sat_normal
    return False


def parse_whatsapp_chat(text_content):
    seferler = []
    # Şoförlerin gruptaki isim takibi
    aktif_isler = {"Önal": None, "Salih": None, "Hasib": None}

    # ÇOK ESNEK REGEX: Köşeli parantez içindeki her türlü tarih ve saat formatını yakalar
    pattern = r"\[(\d+/\d+/\d+),\s+([^\]]+)\]\s+([^:]+):\s+(.*)"

    for line in text_content.split("\n"):
        match = re.match(pattern, line)
        if not match:
            continue

        date_str, time_str, sender, msg = match.groups()

        # Tarih ayrıştırma mekanizması (AM/PM veya 24 saat formatına uyumlu)
        try:
            time_clean = time_str.strip()
            # Eğer saniyeden sonra AM/PM varsa ona göre oku
            if "AM" in time_clean or "PM" in time_clean:
                dt = datetime.datetime.strptime(
                    f"{date_str} {time_clean}", "%m/%d/%y %I:%M:%S %p"
                )
            else:
                dt = datetime.datetime.strptime(
                    f"{date_str} {time_clean}", "%m/%d/%y %H:%M:%S"
                )
        except:
            continue

        # Şoför ismi eşleştirme varyasyonları
        sender_lower = sender.lower()
        driver_name = ""
        if "önal" in sender_lower or "ünal" in sender_lower:
            driver_name = "Önal"
        elif "salih" in sender_lower:
            driver_name = "Salih"
        elif "hasib" in sender_lower or "selahattin" in sender_lower:
            driver_name = "Hasib"

        if not driver_name:
            continue  # Operasyon yöneticisi mesajlarını atla

        msg_lower = msg.lower()

        # Medyasız dökümdeki albüm ve görsel uyarı satırlarını temizleme
        if "<görsel dahil edilmedi>" in msg_lower or "<album mesajı>" in msg_lower:
            msg_clean = (
                msg.replace("<görsel dahil edilmedi>", "")
                .replace("<album mesajı>", "")
                .strip()
            )
            msg_lower = msg_clean.lower()
        else:
            msg_clean = msg.strip()

        if not msg_lower:
            continue

        # --- İŞ BAŞLANGIÇ SİNYALLERİ ---
        is_start = any(
            x in msg_lower
            for x in ["alındı", "başlandı", "çıkış yaptım", "çıkış yapıldı", "yüklendi", "dc"]
        ) and not any(x in msg_lower for x in ["teslim", "edildi", "ettim"])

        # --- İŞ BİTİŞ SİNYALLERİ ---
        is_end = any(
            x in msg_lower for x in ["teslim", "edildi", "ettim", "bitti"]
        )

        is_double_20 = any(x in msg_lower for x in ["çift 20", "2x20", "2*20"])
        job_type = "Soda Operasyonu" if "soda" in msg_lower else "Normal Aktarma"

        if is_start:
            aktif_isler[driver_name] = {
                "start_time": dt,
                "job_type": job_type,
                "double_20": is_double_20,
                "route_details": msg_clean,
            }
        elif is_end:
            # Hafızada bekleyen iş varsa kapat
            if aktif_isler[driver_name] is not None:
                start_info = aktif_isler[driver_name]
                start_is_normal = is_normal_hour(start_info["start_time"])
                end_is_normal = is_normal_hour(dt)

                base_premium = (
                    600 if start_info["job_type"] == "Soda Operasyonu" else 250
                )
                multiplier = (
                    2 if (not start_is_normal and not end_is_normal) else 1
                )

                seferler.append(
                    {
                        "Şoför": driver_name,
                        "Güzergah / İş Detayı": start_info["route_details"],
                        "İş Türü": start_info["job_type"],
                        "İşe Başlama": start_info["start_time"].strftime(
                            "%d/%m/%Y %H:%M"
                        ),
                        "Teslim Etme": dt.strftime("%d/%m/%Y %H:%M"),
                        "Prim Çarpanı": f"{multiplier}X",
                        "Prim Tutarı (TL)": base_premium * multiplier,
                        "Çift 20'lik mi?": (
                            "Evet (Tek Sefer)" if start_info["double_20"] else "Hayır"
                        ),
                    }
                )
                aktif_isler[driver_name] = None
            else:
                # Hafızada iş yoksa ama mesajın kendisi güzergah içeriyorsa (Örn: Demirellerden limana teslim edildi)
                if any(x in msg_lower for x in ["depo", "liman", "ardep", "ciss", "gts"]):
                    start_is_normal = is_normal_hour(dt - datetime.timedelta(hours=1))
                    end_is_normal = is_normal_hour(dt)
                    base_premium = 600 if "soda" in msg_lower else 250
                    multiplier = 2 if (not start_is_normal and not end_is_normal) else 1

                    seferler.append(
                        {
                            "Şoför": driver_name,
                            "Güzergah / İş Detayı": msg_clean,
                            "İş Türü": job_type,
                            "İşe Başlama": "Doğrudan Teslim Bildirimi",
                            "Teslim Etme": dt.strftime("%d/%m/%Y %H:%M"),
                            "Prim Çarpanı": f"{multiplier}X",
                            "Prim Tutarı (TL)": base_premium * multiplier,
                            "Çift 20'lik mi?": (
                                "Evet (Tek Sefer)" if is_double_20 else "Hayır"
                            ),
                        }
                    )

    return pd.DataFrame(seferler)


# --- STREAMLIT MOBIL ARAYÜZ TASARIMI ---
st.set_page_config(page_title="Tır Optimizasyon v1.2", layout="centered")

st.title("🚛 Nakliye Maliyet & Rota Optimizasyonu")
st.caption("Medyasız WhatsApp Metin Okuma Filtresi Aktif")

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

st.subheader("📂 Veri Giriş Kaynakları")
whatsapp_file = st.file_uploader(
    "WhatsApp Sohbet Dökümünü (.txt veya .md) Yükleyin", type=["txt", "md"]
)

if whatsapp_file is not None:
    chat_text = whatsapp_file.read().decode("utf-8")
    df_seferler = parse_whatsapp_chat(chat_text)

    if not df_seferler.empty:
        st.success(
            f"✅ Toplam {len(df_seferler)} adet tamamlanmış sefer başarıyla bağlandı!"
        )

        st.subheader("📊 Dönemlik Finansal Özet")
        col1, col2 = st.columns(2)

        toplam_prim = df_seferler["Prim Tutarı (TL)"].sum()

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
                label="Brüt Ciro (KDV Dahil)", value=f"{toplam_ciro:,.2f} TL"
            )
            st.metric(label="Toplam Şoför Primleri", value=f"{toplam_prim:,} TL")
        with col2:
            st.metric(label="Yakıt Gideri", value=f"{toplam_yakit_maliyeti:,} TL")
            st.metric(
                label="Tahmini Net Kar",
                value=f"{net_kar:,.2f} TL",
                delta=f"%{((net_kar/toplam_ciro)*100 if toplam_ciro > 0 else 0):.1f} Verimlilik",
            )

        st.subheader("📋 Sefer Detay Listesi")
        st.dataframe(df_seferler, use_container_width=True)
    else:
        st.error(
            "Yüklenen dosya formatı çözülemedi. Lütfen şoförlerin gruptaki isimlerini veya mesaj biçimlerini kontrol edin."
        )
