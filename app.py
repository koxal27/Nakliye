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
    """Geliştirilmiş Akıllı Eşleştirme Motoru"""
    seferler = []
    # Her şoförün en son başladığı aktif işi hafızada tutan havuz
    aktif_isler = {
        "Önal": None,
        "Salih": None,
        "Hasib": None,
    }

    # WhatsApp satır yakalama şablonları (.txt ve .md uyumlu)
    pattern_txt = r"\[(\d+/\d+/\d+),\s+(\d+:\d+:\d+\s+[AP]M)\]\s+([^:]+):\s+(.*)"
    pattern_md = r"\[(\d+:\d+)\]\s+\*\*([^\*]+):\*\*\s+(.*)"

    for line in text_content.split("\n"):
        driver_name = ""
        msg = ""
        dt = None

        # 1. Format Denemesi (.txt formatı)
        match = re.match(pattern_txt, line)
        if match:
            date_str, time_str, sender, msg = match.groups()
            try:
                dt_str = f"{date_str} {time_str}"
                dt = datetime.datetime.strptime(dt_str, "%m/%d/%y %I:%M:%S %p")
            except:
                continue
        else:
            # 2. Format Denemesi (.md formatı)
            match = re.match(pattern_md, line)
            if match:
                time_str, sender, msg = match.groups()
                # .md formatında tam tarih üst satırlarda kalabildiği için bugünün tarihini geçici atıyoruz
                try:
                    today = datetime.date.today()
                    dt_time = datetime.datetime.strptime(time_str, "%H:%M").time()
                    dt = datetime.datetime.combine(today, dt_time)
                except:
                    continue
            else:
                continue

        # Şoför ismi eşleştirme (Gruptaki yazım varyasyonlarına göre)
        sender_lower = sender.lower()
        if "önal" in sender_lower or "ünal" in sender_lower:
            driver_name = "Önal"
        elif "salih" in sender_lower:
            driver_name = "Salih"
        elif "hasib" in sender_lower:
            driver_name = "Hasib"

        if not driver_name:
            continue

        msg_lower = msg.lower()

        # --- İŞ BAŞLANGIÇ SİNYALLERİ ---
        is_start = any(
            x in msg_lower
            for x in [
                "alındı",
                "başlandı",
                "çıkış yaptım",
                "çıkış yapıldı",
                "hazır",
                "yüklendi",
                "dc",
            ]
        ) and not any(x in msg_lower for x in ["teslim", "ettim", "edildi"])

        # --- İŞ BİTİŞ SİNYALLERİ ---
        is_end = any(
            x in msg_lower
            for x in ["teslim", "edildi", "ettim", "bitti", "boş teslim"]
        )

        # Çift 20'lik konteynır analizi
        is_double_20 = "çift 20" in msg_lower or "2x20" in msg_lower or "2*20" in msg_lower

        # İş türü
        job_type = "Soda Operasyonu" if "soda" in msg_lower else "Normal Aktarma"

        if is_start:
            # Şoför yeni işe başladı, havuzu güncelle
            aktif_isler[driver_name] = {
                "start_time": dt,
                "job_type": job_type,
                "double_20": is_double_20,
                "route_details": msg,
            }
        elif is_end:
            # Şoför "Teslim ettim" dedi. Havuzda bu şoförün bekleyen işi var mı?
            if aktif_isler[driver_name] is not None:
                start_info = aktif_isler[driver_name]

                # Prim kurallarını işlet
                start_is_normal = is_normal_hour(start_info["start_time"])
                end_is_normal = is_normal_hour(dt)

                base_premium = (
                    600 if start_info["job_type"] == "Soda Operasyonu" else 250
                )
                # Kural C: Hem alış hem bırakış mesai dışındaysa ÇİFT PRİM
                multiplier = (
                    2 if (not start_is_normal and not end_is_normal) else 1
                )
                final_premium = base_premium * multiplier

                seferler.append(
                    {
                        "Şoför": driver_name,
                        "Güzergah/İş Bilgisi": start_info["route_details"],
                        "Yük Tipi": start_info["job_type"],
                        "İş Başlangıç": start_info["start_time"].strftime(
                            "%d/%m/%Y %H:%M"
                        ),
                        "Teslim Saati": dt.strftime("%d/%m/%Y %H:%M"),
                        "Prim Çarpanı": f"{multiplier}X",
                        "Kazanılan Prim (TL)": final_premium,
                        "Çift 20'lik Seferi": (
                            "Evet (Tek Sefer)"
                            if start_info["double_20"]
                            else "Hayır"
                        ),
                    }
                )
                # İşi başarıyla kapattık, şoförün havuzunu boşalt
                aktif_isler[driver_name] = None
            else:
                # Eğer havuzda iş yoksa ama şoför doğrudan güzergah belirterek teslim ettim dediyse (Örn: Ardepten limana teslim edildi)
                if any(x in msg_lower for x in ["depodan", "limana", "ardep"]):
                    start_is_normal = is_normal_hour(dt - datetime.timedelta(hours=1)) # Tahmini 1 saat önce başladı varsayımı
                    end_is_normal = is_normal_hour(dt)
                    base_premium = 600 if "soda" in msg_lower else 250
                    multiplier = 2 if (not start_is_normal and not end_is_normal) else 1
                    
                    seferler.append({
                        "Şoför": driver_name,
                        "Güzergah/İş Bilgisi": msg,
                        "Yük Tipi": job_type,
                        "İş Başlangıç": "Doğrudan Teslim Bildirimi",
                        "Teslim Saati": dt.strftime("%d/%m/%Y %H:%M"),
                        "Prim Çarpanı": f"{multiplier}X",
                        "Kazanılan Prim (TL)": base_premium * multiplier,
                        "Çift 20'lik Seferi": "Evet (Tek Sefer)" if is_double_20 else "Hayır"
                    })

    return pd.DataFrame(seferler)


# --- STREAMLIT MOBIL ARAYÜZ TASARIMI ---
st.set_page_config(page_title="Tır Optimizasyon v1.1", layout="centered")

st.title("🚛 Nakliye Maliyet & Rota Optimizasyonu")
st.caption("Geliştirilmiş Akıllı Mesaj Eşleştirme Motoru Aktif")

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
            f"✅ Toplam {len(df_seferler)} adet tamamlanmış sefer başarıyla eşleştirildi ve bağlandı!"
        )

        st.subheader("📊 Dönemlik Finansal Özet")
        col1, col2 = st.columns(2)

        toplam_prim = df_seferler["Kazanılan Prim (TL)"].sum()

        toplam_ciro = 0
        for _, row in df_seferler.iterrows():
            fiyat = (
                SODA_FIYAT_BASE
                if row["Yük Tipi"] == "Soda Operasyonu"
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
                delta=f"%{((net_kar/toplam_ciro)*100 if toplam_ciro > 0 else 0):.1f} Yol Verimliliği",
            )

        st.subheader("📋 Sefer Detay Listesi")
        st.dataframe(df_seferler, use_container_width=True)
    else:
        st.error(
            "Yüklenen dosya okundu ancak şoförlerin iş bitiş/teslim bildirimleri ile güzergah başlangıçları eşleştirilemedi. Lütfen şoförlerin gruptaki isimlerini veya mesaj biçimlerini kontrol edin."
        )
