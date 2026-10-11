import datetime
import pandas as pd
import streamlit as st

# --- MERSİN NAKLİYE PARAMETRELERİ (KDV %16) ---
KDV_ORANI = 0.16
SODA_FIYAT_BASE = 4700.0

DEPO_FIYATLARI = {
    "Soda Operasyonu (MDR)": 4700.0,
    "Ardep (Çilek Mahallesi)": 3800.0,
    "GTS / GTS-1 / GTS-3": 3600.0,
    "CCIS / CISS Depo": 3700.0,
    "Demireller / Falcon": 3500.0,
    "OLS Depo": 3400.0
}

SABIT_SIGORTA_AYLIK = 82000 / 12
SABIT_PERSONEL_AYLIK = 42000 + 12000
SABIT_SANAYI_AYLIK = 600000 / 3 / 12
TOPLAM_AYLIK_SABIT_GIDER_TIR_BASI = SABIT_SIGORTA_AYLIK + SABIT_PERSONEL_AYLIK + SABIT_SANAYI_AYLIK


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


def parse_whatsapp_media_count(text_content):
    seferler = []
    text_content = text_content.replace("\x00", "").replace("\ufeff", "").replace("\r", "")
    satirlar = text_content.split("\n")

    last_media_time = {}  # Peş peşe atılan resimleri (çift 20'lik vb.) korumak için zaman kilidi

    for satir in satirlar:
        satir = satir.strip()
        if not satir or " - " not in satir or ":" not in satir:
            continue

        satir_lower = satir.lower()

        # DOSYADA MEDYA VARLIĞI TESPİTİ (Fotoğraf atılmışsa tetiklenir)
        is_media = "<medya dahil edilmedi>" in satir_lower or "görsel" in satir_lower or "<görsel dahil edilmedi>" in satir_lower

        if not is_media:
            continue

        try:
            timestamp_part, remainder = satir.split(" - ", 1)
            sender_part, _ = remainder.split(":", 1)
        except:
            continue

        sender_lower = sender_part.lower()
        driver_name = ""
        if "önal" in sender_lower or "ünal" in sender_lower: driver_name = "Önal"
        elif "salih" in sender_lower: driver_name = "Salih"
        elif "hasib" in sender_lower or "selahattin" in sender_lower: driver_name = "Hasib"

        if not driver_name:
            continue

        # Tarih İşleme
        try:
            if "[" in timestamp_part:
                timestamp_part = timestamp_part.replace("[", "").replace("]", "")
            dt = datetime.datetime.strptime(timestamp_part.strip(), "%d.%m.%Y %H:%M")
        except:
            continue

        # ÇİFT 20'LİK / PEŞ PEŞE RESİM KONTROLÜ (5 dakika içinde atılan resimler tek sefer sayılır)
        if driver_name in last_media_time:
            zaman_farki = (dt - last_media_time[driver_name]).total_seconds() / 60
            if zaman_farki <= 5:  # 5 dakika içinde peş peşe gelen mühür/konteynır resimleri tek iş kabul edilir
                continue

        last_media_time[driver_name] = dt

        # Prim Durumu (Resmin grupta paylaşıldığı saniyeye göre)
        is_normal = is_normal_hour(dt)
        multiplier = 1 if is_normal else 2

        # Varsayılan hat ataması (Kullanıcı panelden değiştirebilir)
        hat = "Belirlenmedi (Lütfen Seçin)"
        if "soda" in satir_lower: hat = "Soda Operasyonu (MDR)"
        elif "ardep" in satir_lower: hat = "Ardep (Çilek Mahallesi)"
        elif "gts" in satir_lower: hat = "GTS / GTS-1 / GTS-3"
        elif "ccis" in satir_lower or "cıss" in satir_lower: hat = "CCIS / CISS Depo"
        elif "demirel" in satir_lower or "falcon" in satir_lower: hat = "Demireller / Falcon"

        base_premium = 600 if hat == "Soda Operasyonu (MDR)" else 250

        seferler.append({
            "Şoför": driver_name,
            "Resim Atılma Zamanı": dt.strftime("%d/%m/%Y %H:%M"),
            "Güzergah / Depo": hat,
            "Prim Durumu": f"{multiplier}X Prim",
            "Hak Ediş Prim (TL)": base_premium * multiplier,
            "İş Durumu": "Resim Geldi (Sefer Onaylandı)"
        })

    return pd.DataFrame(seferler)


# --- STREAMLIT ARAYÜZÜ ---
st.set_page_config(page_title="Mersin Fotoğraflı Konteynır Takip", layout="centered")
st.title("📸 Fotoğraf Sayım Tabanlı Nakliye Takibi")
st.caption("Yazılara takılmayan, sadece konteynır/mühür fotoğraflarına odaklanan akıllı sistem")

st.sidebar.header("⛽ Günlük Yakıt Girişleri")
mazot_litre = st.sidebar.number_input("Toplam Alınan Mazot (Litre)", min_value=0.0, value=150.0)
mazot_fiyat = st.sidebar.number_input("Mazot Litre Fiyatı (TL)", min_value=0.0, value=43.10)
toplam_yakit_maliyeti = mazot_litre * mazot_fiyat

st.sidebar.markdown("---")
st.sidebar.subheader("📅 Sabit Giderler")
st.sidebar.write(f"Tır Başı Aylık Gider: **{TOPLAM_AYLIK_SABIT_GIDER_TIR_BASI:,.2f} TL**")

whatsapp_file = st.file_uploader("WhatsApp Medyasız Dışa Aktarılan .txt Dosyasını Yükleyin", type=["txt"])

if whatsapp_file is not None:
    chat_text = whatsapp_file.read().decode("utf-8", errors="ignore")
    df = parse_whatsapp_media_count(chat_text)

    if not df.empty:
        st.success(f"✅ Başarılı! Grupta şoförlere ait {len(df)} adet bağımsız Konteynır/Mühür resmi tespit edildi!")

        st.subheader("📝 Depo Seçim Alanı")
        st.caption("Resimlerin hangi depoya ait olduğunu aşağıdaki listelerden işaretleyerek net karınızı görebilirsiniz:")
        
        updated_seferler = []
        for idx, row in df.iterrows():
            with st.expander(f"📸 {row['Şoför']} - {row['Resim Atılma Zamanı']}"):
                default_idx = 0
                if row["Güzergah / Depo"] != "Belirlenmedi (Lütfen Seçin)":
                    default_idx = list(DEPO_FIYATLARI.keys()).index(row["Güzergah / Depo"])
                
                secilen_depo = st.selectbox(
                    f"Güzergah Seçin ({row['Resim Atılma Zamanı']})", 
                    list(DEPO_FIYATLARI.keys()), 
                    index=default_idx,
                    key=f"depo_{idx}"
                )
                
                row["Güzergah / Depo"] = secilen_depo
                # Prim güncelleme
                base_p = 600 if secilen_depo == "Soda Operasyonu (MDR)" else 250
                mult = 2 if "2X" in row["Prim Durumu"] else 1
                row["Hak Ediş Prim (TL)"] = base_p * mult
                
                updated_seferler.append(row)
        
        df_final = pd.DataFrame(updated_seferler)

        # --- FİNANSAL HESAPLAMALAR ---
        st.subheader("📊 Operasyonel Maliyet ve Kar Raporu")
        toplam_prim = df_final["Hak Ediş Prim (TL)"].sum()
        toplam_ciro = sum(DEPO_FIYATLARI[r["Güzergah / Depo"]] * (1 + KDV_ORANI) for _, r in df_final.iterrows())
        net_kar = toplam_ciro - toplam_prim - toplam_yakit_maliyeti

        col1, col2 = st.columns(2)
        with col1:
            st.metric(label="Net Ciro (KDV Dahil)", value=f"{toplam_ciro:,.2f} TL")
            st.metric(label="Toplam Şoför Primleri", value=f"{toplam_prim:,} TL")
        with col2:
            st.metric(label="Yakıt Maliyeti", value=f"{toplam_yakit_maliyeti:,} TL")
            st.metric(label="Net Yol Karı", value=f"{net_kar:,.2f} TL")

        st.subheader("📋 Kesinleşen Sefer Listesi")
        st.dataframe(df_final[["Şoför", "Resim Atılma Zamanı", "Güzergah / Depo", "Prim Durumu", "Hak Ediş Prim (TL)"]], use_container_width=True)
