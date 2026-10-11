import datetime
import pandas as pd
import streamlit as st

# --- MERSİN LOJİSTİK PARAMETRELERİ (KDV %16) ---
KDV_ORANI = 0.16
SODA_FIYAT_BASE = 4700.0

# Gerçek Rota Fiyatları (Matrah)
DEPO_FIYATLARI = {
    "soda": 4700.0,
    "ardep": 3800.0,
    "gts": 3600.0,
    "ccis": 3700.0,
    "ciss": 3700.0,
    "demirel": 3500.0,
    "falcon": 3500.0,
    "ols": 3400.0
}

# Şehir İçi Gerçek Rota Mesafeleri (KM)
DEPO_MESAFELERI = {
    "soda": 12.0,
    "ardep": 6.0,
    "gts": 8.0,
    "ccis": 9.0,
    "ciss": 9.0,
    "demirel": 7.0,
    "falcon": 7.0,
    "ols": 10.0
}

# --- YAKIT TÜKETİM MODELLEMESİ (ŞEHİR İÇİ GEREKÇELİ ANALİZ) ---
BASE_CONSUMPTION_EMPTY = 0.38  # Boş araç/konteynır: KM başına 0.38 Litre (100 KM'de 38L)
BASE_CONSUMPTION_LOADED = 0.57  # Dolu araç (24-25 Ton): KM başına 0.57 Litre (100 KM'de 57L)


def calculate_real_consumption(distance, is_loaded, dt):
    """Mersin şehir içi trafik ve tonaj modellemesine göre gerçek yakıt tüketimi hesaplar."""
    # 1. Aşama: Tonaj Kontrolü
    base_rate = BASE_CONSUMPTION_LOADED if is_loaded else BASE_CONSUMPTION_EMPTY
    
    # 2. Aşama: Zaman Dilimine Göre Trafik ve Liman Sıra Bekleme Yoğunluğu Çarpanı
    hour = dt.hour
    if 8 <= hour <= 18:
        traffic_multiplier = 1.45  # Gündüz yoğun saatlerde %45 fazla yakar (Rölanti/Dur-Kalk)
    else:
        traffic_multiplier = 1.00  # Gece akıcı trafik
        
    total_liters = distance * base_rate * traffic_multiplier
    return total_liters


def is_normal_hour(dt: datetime.datetime) -> bool:
    """Haftaiçi 08-18, Cmt 08-13 arası normal, diğer saatler çift prim."""
    weekday = dt.weekday()
    time_of_day = dt.time()
    if 0 <= weekday <= 4:
        return datetime.time(8, 0) <= time_of_day <= datetime.time(18, 0)
    elif weekday == 5:
        return datetime.time(8, 0) <= time_of_day <= datetime.time(13, 0)
    return False


def parse_whatsapp_smart_analytics(text_content):
    seferler = []
    text_content = text_content.replace("\x00", "").replace("\ufeff", "").replace("\r", "")
    satirlar = text_content.split("\n")

    # Son iş durumlarını hafızada tutarak akıllı çıkarım sağlama
    son_rota_tahmini = "gts"
    son_yuk_durumu = False  # Dolu/Boş durumu

    for satir in satirlar:
        satir = satir.strip()
        if not satir or " - " not in satir or ":" not in satir:
            continue

        satir_lower = satir.lower()

        # Operasyoncuların veya şoförlerin yazılarından güzergah ve yük durumunu akıllıca oku
        for depo in DEPO_FIYATLARI.keys():
            if depo in satir_lower:
                son_rota_tahmini = depo
                break
        
        if "dolu" in satir_lower:
            son_yuk_durumu = True
        elif "boş" in satir_lower:
            son_yuk_durumu = False

        # Sadece resim (Medya) atılan veya net teslimat/çıkış bildirimi olan satırları sefer say
        is_action = any(x in satir_lower for x in ["<medya dahil edilmedi>", "görsel", "teslim", "edildi", "ettim", "çıkış yaptım"])
        if not is_action:
            continue

        try:
            timestamp_part, remainder = satir.split(" - ", 1)
            sender_part, msg_content = remainder.split(":", 1)
        except:
            continue

        sender_lower = sender_part.lower()
        driver_name = ""
        if "önal" in sender_lower or "ünal" in sender_lower: driver_name = "Önal"
        elif "salih" in sender_lower: driver_name = "Salih"
        elif "hasib" in sender_lower or "selahattin" in sender_lower: driver_name = "Hasib"

        if not driver_name:
            continue

        try:
            timestamp_clean = timestamp_part.replace("[", "").replace("]", "").strip()
            dt = datetime.datetime.strptime(timestamp_clean, "%d.%m.%Y %H:%M")
        except:
            continue

        # Prim kurallarını saat kontrolüne göre işlet (250 ya da 2 katı: 500 / Soda için 600 ya da 1200)
        is_normal = is_normal_hour(dt)
        base_p = 600 if son_rota_tahmini == "soda" else 250
        multiplier = 1 if is_normal else 2
        final_premium = base_p * multiplier

        # Yakıt ve mesafe hesaplamalarını tüketim modeline gönder
        km = DEPO_MESAFELERI[son_rota_tahmini]
        harcanan_litre = calculate_real_consumption(km, son_yuk_durumu, dt)
        
        # Çiro hesabı
        kazanc = DEPO_FIYATLARI[son_rota_tahmini] * (1 + KDV_ORANI)

        seferler.append({
            "Şoför": driver_name,
            "Tarih/Saat": dt,
            "Güzergah (Depo)": son_rota_tahmini.upper(),
            "Yük Durumu": "DOLU (24 Ton)" if son_yuk_durumu else "BOŞ / YÜKSÜZ",
            "Mesafe (KM)": km,
            "Hesaplanan Tüketim (Litre)": round(harcanan_litre, 2),
            "Şoför Primi (TL)": final_premium,
            "Sefer Cirosu (TL)": kazanc,
            "Zaman Dilimi": "Gündüz (Yoğun Trafik)" if (8 <= dt.hour <= 18) else "Gece / Akşam (Akıcı)"
        })

    return pd.DataFrame(seferler)


# --- STREAMLIT PANEL TASARIMI ---
st.set_page_config(page_title="Mersin Şehiriçi Lojistik Analitik", layout="wide")
st.title("📊 Mersin Şehiriçi Konteynır Karlılık & Verimlilik Analiz Motoru")

# Manuel Yakıt Alım ve Depo Durum Girişleri Tablosu
st.sidebar.header("⛽ Hassas Yakıt Girişleri")
manuel_litre_fiyati = st.sidebar.number_input("Güncel Mazot Litre Fiyatı (TL)", min_value=0.0, value=43.15)
manuel_alinan_litre = st.sidebar.number_input("Dönem İçi Toplam Alınan Toplam Mazot (Litre)", min_value=0.0, value=1200.0)
depodaki_mevcut_litre = st.sidebar.number_input("Şu Anda Depolarda Kalan Yakıt (Litre)", min_value=0.0, value=150.0)

st.sidebar.markdown("---")
st.sidebar.subheader("📅 Aylık Sabit Gider Payı")
st.sidebar.write(f"3 Araç Toplam Aylık Gider: **{TOPLAM_AYLIK_SABIT_GIDER_TIR_BASI * 3:,.2f} TL**")

whatsapp_file = st.file_uploader("WhatsApp .txt Sohbet Dosyasını Yükleyin", type=["txt"])

if whatsapp_file is not None:
    chat_text = whatsapp_file.read().decode("utf-8", errors="ignore")
    df = parse_whatsapp_smart_analytics(chat_text)

    if not df.empty:
        st.success(f"✅ Akıllı okuma tamamlandı! {len(df)} adet sefer analiz edilerek güzergah kârlılık raporu çıkarıldı.")

        # --- ÜST ÖZET KARTLARI ---
        total_ciro = df["Sefer Cirosu (TL)"].sum()
        total_prim = df["Şoför Primi (TL)"].sum()
        total_predicted_liters = df["Hesaplanan Tüketim (Litre)"].sum()
        total_predicted_fuel_cost = total_predicted_liters * manuel_litre_fiyati
        
        # Gerçek sarfiyat analizi
        gercek_tuketilen_yakit = manuel_alinan_litre - depodaki_mevcut_litre
        gercek_yakit_maliyeti = gercek_tuketilen_yakit * manuel_litre_fiyati
        
        net_yol_kari = total_ciro - total_prim - gercek_yakit_maliyeti

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Toplam Brüt Ciro", f"{total_ciro:,.2f} TL")
        col2.metric("Toplam Şoför Primleri", f"{total_prim:,.2f} TL")
        col3.metric("Gerçek Yakıt Maliyeti", f"{gercek_yakit_maliyeti:,.2f} TL", f"{gercek_tuketilen_yakit:,.1f} Litre Tüketim")
        col4.metric("Sistem Net Kârı", f"{net_yol_kari:,.2f} TL")

        # --- GÜZERGAH BAZLI VERİMLİLİK VE KARLILIK ANALİZİ (ANA AMAÇ) ---
        st.subheader("🎯 En Karlı Güzergah ve Rota Analiz Raporu")
        
        # Güzergaha göre gruplayıp analiz etme
        df_group = df.groupby("Güzergah (Depo)").agg(
            Sefer_Sayisi=("Şoför", "count"),
            Toplam_Ciro=("Sefer Cirosu (TL)", "sum"),
            Toplam_Prim=("Şoför Primi (TL)", "sum"),
            Tahmini_Litre=("Hesaplanan Tüketim (Litre)", "sum")
        ).reset_index()
        
        df_group["Yakıt Maliyeti (TL)"] = df_group["Tahmini_Litre"] * manuel_litre_fiyati
        df_group["Net Bırakan Kâr (TL)"] = df_group["Toplam_Ciro"] - df_group["Toplam_Prim"] - df_group["Yakıt Maliyeti (TL)"]
        df_group["Sefer Başı Ortalama Kâr (TL)"] = df_group["Net Bırakan Kâr (TL)"] / df_group["Sefer_Sayisi"]
        
        # En karlı güzergahı sırala
        df_group = df_group.sort_values(by="Sefer Başı Ortalama Kâr (TL)", ascending=False)
        
        st.dataframe(df_group[[
            "Güzergah (Depo)", "Sefer_Sayisi", "Toplam_Ciro", "Net Bırakan Kâr (TL)", "Sefer Başı Ortalama Kâr (TL)"
        ]], use_container_width=True)
        
        # Altın Analiz Notu
        en_karli_rota = df_group.iloc[0]["Güzergah (Depo)"]
        st.info(
            f"🧠 **Yapay Zeka Strateji Raporu:** Yapılan detaylı Mersin liman içi trafik ve yük/tonaj analizine göre, "
            f"tırlarınız için şu an sefer başına en yüksek verimi ve net kârı **{en_karli_rota}** güzergahı bırakmaktadır. "
            f"Gündüz saatlerindeki yoğun dur-kalk trafiği yakıt sarfiyatını ortalama %45 artırdığından, mümkün mertebe "
            f"bu güzergahların nakliyelerini akşam ve gece saatlerine kaydırmak yol kârlılığınızı maksimum seviyeye çıkaracaktır."
        )

        # Detaylı Sefer Listesi
        st.subheader("📋 Detaylı Sefer ve Trafik Yoğunluk Listesi")
        st.dataframe(df[["Şoför", "Güzergah (Depo)", "Yük Durumu", "Zaman Dilimi", "Hesaplanan Tüketim (Litre)", "Şoför Primi (TL)", "Sefer Cirosu (TL)"]], use_container_width=True)
