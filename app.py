import datetime
import pandas as pd
import streamlit as st

# --- MERSİN LOJİSTİK PARAMETRELERİ ---
KDV_ORANI = 0.16
SODA_FIYAT_BASE = 4700.0

SABIT_SIGORTA_AYLIK = 82000 / 12
SABIT_PERSONEL_AYLIK = 42000 + 12000
SABIT_SANAYI_AYLIK = 600000 / 3 / 12
TOPLAM_AYLIK_SABIT_GIDER_TIR_BASI = (
    SABIT_SIGORTA_AYLIK + SABIT_PERSONEL_AYLIK + SABIT_SANAYI_AYLIK
)


def is_normal_hour(dt: datetime.datetime) -> bool:
    """Haftaiçi 08-18, Cmt 08-13 arası normal prim, diğer zamanlar çift prim."""
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


def parse_whatsapp_bulletproof_final(text_content):
    seferler = []
    # Kim ne iş yapıyor takibi için aktif havuz
    aktif_isler = {}

    text_content = (
        text_content.replace("\x00", "")
        .replace("\ufeff", "")
        .replace("\r", "")
    )
    satirlar = text_content.split("\n")

    base_date = datetime.date(2026, 10, 5)

    for satir in satirlar:
        satir = satir.strip()
        if not satir or "[" not in satir or "]" not in satir:
            continue

        satir_lower = satir.lower()

        # Köşeli parantez içinden zamanı temizle
        try:
            close_idx = satir.find("]")
            timestamp_part = satir[1:close_idx].strip()
            remainder = satir[close_idx + 1 :].strip()
            if remainder.startswith("-"):
                remainder = remainder[1:].strip()

            if ":" in remainder:
                sender_part, msg_clean = remainder.split(":", 1)
            else:
                sender_part = "Bilinmeyen Şoför"
                msg_clean = remainder
        except:
            continue

        sender_clean = sender_part.replace("**", "").strip()
        sender_lower = sender_clean.lower()

        # Sistemdeki şoför kimliklerini sadeleştirme
        driver_name = "Diğer/Yönetici"
        if "önal" in sender_lower or "ünal" in sender_lower:
            driver_name = "Önal"
        elif "salih" in sender_lower:
            driver_name = "Salih"
        elif "hasib" in sender_lower or "selahattin" in sender_lower or "alc 272" in sender_lower:
            driver_name = "Hasib"
        elif "garaj" in sender_lower:
            driver_name = "Önal"  # Garaj hesabından yazılan iş başlangıçları için emniyet

        # Tarih formatı esnetme
        dt = None
        time_formats = [
            "%m/%d/%y, %I:%M:%S %p",
            "%m/%d/%y, %H:%M:%S",
            "%d.%m.%Y %H:%M",
            "%m/%d/%y, %I:%M %p",
            "%H:%M",
        ]
        for tf in time_formats:
            try:
                dt = datetime.datetime.strptime(timestamp_part, tf)
                break
            except:
                continue

        if not dt:
            try:
                dt_time = datetime.datetime.strptime(timestamp_part, "%H:%M").time()
                dt = datetime.datetime.combine(base_date, dt_time)
            except:
                continue

        msg_clean = (
            msg_clean.replace("<görsel dahil edilmedi>", "")
            .replace("<album mesajı>", "")
            .replace("[Görsel]", "")
            .strip()
        )
        msg_lower = msg_clean.lower()

        if not msg_lower or "grubu oluşturdu" in msg_lower or "kişilerini ekledi" in msg_lower:
            continue

        # --- LOJİSTİK HAREKET DETAYLARI ---
        is_start = any(
            x in msg_lower
            for x in ["alındı", "başlandı", "yüklendi", "boşu alındı", "hazır", "çıkış yaptım", "çıkış yapıldı"]
        ) and not any(x in msg_lower for x in ["teslim", "edildi", "ettim"])

        is_end = any(
            x in msg_lower for x in ["teslim", "edildi", "ettim", "bitti", "boş teslim"]
        )

        is_double_20 = any(x in msg_lower for x in ["çift 20", "2x20", "2*20"])
        job_type = "Soda Operasyonu" if "soda" in msg_lower else "Normal Aktarma"

        if is_start and driver_name != "Diğer/Yönetici":
            aktif_isler[driver_name] = {
                "start_time": dt,
                "job_type": job_type,
                "double_20": is_double_20,
                "route_details": msg_clean[:60],
            }
        elif is_end and driver_name != "Diğer/Yönetici":
            if driver_name in aktif_isler and aktif_isler[driver_name] is not None:
                start_info = aktif_isler[driver_name]
                start_is_normal = is_normal_hour(start_info["start_time"])
                end_is_normal = is_normal_hour(dt)

                base_premium = 600 if start_info["job_type"] == "Soda Operasyonu" else 250
                multiplier = 2 if (not start_is_normal and not end_is_normal) else 1

                seferler.append(
                    {
                        "Şoför": driver_name,
                        "Güzergah / İş Bildirimi": start_info["route_details"],
                        "İş Tipi": start_info["job_type"],
                        "İşe Başlama": start_info["start_time"].strftime("%d/%m/%Y %H:%M"),
                        "Teslimat Saati": dt.strftime("%d/%m/%Y %H:%M"),
                        "Prim Tipi": f"{multiplier}X",
                        "Hak Ediş (TL)": base_premium * multiplier,
                        "Çift 20'lik mi?": "Evet" if start_info["double_20"] else "Hayır",
                    }
                )
                aktif_isler[driver_name] = None
            else:
                # Emniyet Modu: Doğrudan teslim mesajından sefer üret
                if any(x in msg_lower for x in ["depo", "liman", "ardep", "ciss", "gts", "falcon", "demirel"]):
                    start_is_normal = is_normal_hour(dt - datetime.timedelta(hours=1))
                    end_is_normal = is_normal_hour(dt)
                    base_premium = 600 if "soda" in msg_lower else 250
                    multiplier = 2 if (not start_is_normal and not end_is_normal) else 1

                    seferler.append(
                        {
                            "Şoför": driver_name,
                            "Güzergah / İş Bildirimi": msg_clean[:60],
                            "İş Tipi": job_type,
                            "İşe Başlama": "Teslim Bildiriminden Yakalandı",
                            "Teslimat Saati": dt.strftime("%d/%m/%Y %H:%M"),
                            "Prim Tipi": f"{multiplier}X",
                            "Hak Ediş (TL)": base_premium * multiplier,
                            "Çift 20'lik mi?": "Evet" if is_double_20 else "Hayır",
                        }
                    )

    return pd.DataFrame(seferler)


# --- STREAMLIT ARAYÜZÜ ---
st.set_page_config(page_title="Mersin Konteynır Takip", layout="centered")

st.title("🚛 Tır Maliyet & Rota Optimizasyonu")
st.caption("Geliştirilmiş Esnek Metin İşleme Modülü")

st.sidebar.header("⛽ Günlük Yakıt Girişleri")
mazot_litre = st.sidebar.number_input("Toplam Alınan Mazot (Litre)", min_value=0.0, value=150.0)
mazot_fiyat = st.sidebar.number_input("Mazot Litre Fiyatı (TL)", min_value=0.0, value=43.10)
toplam_yakit_maliyeti = mazot_litre * mazot_fiyat

st.sidebar.markdown("---")
st.sidebar.subheader("📅 Aylık Sabit Gider Bilgisi")
st.sidebar.info(f"Araç Başı Sabit Gider: \n**{TOPLAM_AYLIK_SABIT_GIDER_TIR_BASI:,.2f} TL**")

st.subheader("📂 Veri Giriş Kaynakları")
whatsapp_file = st.file_uploader("WhatsApp Sohbet Dökümünü Yükleyin", type=["txt", "md"])

if whatsapp_file is not None:
    chat_text = whatsapp_file.read().decode("utf-8", errors="ignore")
    df_seferler = parse_whatsapp_bulletproof_final(chat_text)

    if not df_seferler.empty:
        st.success(f"✅ Başarılı! {len(df_seferler)} adet sefer hesaplandı ve listelendi!")

        st.subheader("📊 Dönemlik Finansal Rapor")
        col1, col2 = st.columns(2)

        toplam_prim = df_seferler["Hak Ediş (TL)"].sum()

        toplam_ciro = 0
        for _, row in df_seferler.iterrows():
            fiyat = SODA_FIYAT_BASE if row["İş Tipi"] == "Soda Operasyonu" else 3500.0
            toplam_ciro += fiyat * (1 + KDV_ORANI)

        net_kar = toplam_ciro - toplam_prim - toplam_yakit_maliyeti

        with col1:
            st.metric(label="Brüt Ciro (KDV Dahil)", value=f"{toplam_ciro:,.2f} TL")
            st.metric(label="Toplam Ödenen Prim", value=f"{toplam_prim:,} TL")
        with col2:
            st.metric(label="Yakıt Maliyeti", value=f"{toplam_yakit_maliyeti:,} TL")
            st.metric(label="Net Kar (Yol)", value=f"{net_kar:,.2f} TL")

        st.subheader("📋 Hesaplanan Sefer Detayları")
        st.dataframe(df_seferler, use_container_width=True)
    else:
        st.error("Yüklenen dosya okundu ancak geçerli nakliye güzergahı içeren satırlar ayrıştırılamadı. Lütfen şoför mesaj formatından emin olun.")
