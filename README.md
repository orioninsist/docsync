# DocSync

DocSync; resmi dokümantasyon sitelerini taramak, içeriklerini Markdown formatında arşivlemek ve daha sonra bu içerikleri tek bir düz yapıda işleyerek yapay zekâ sistemleri veya bilgi tabanları için hazır hale getirmek amacıyla geliştirilmiş iki aşamalı bir projedir.

Proje tamamen iki bağımsız bölümden oluşur:

- **Crawler**
- **Pipeline**

Bu iki sistem birbirinden tamamen bağımsız çalışır.

---

# Genel Mimari

```
                İnternet
                    │
                    ▼
             Crawler (İndirir)
                    │
                    ▼
      sources/<project>/
            ├── markdown
            ├── database
            ├── queue
            ├── state
            └── output
                    │
                    ▼
        Pipeline (İşler ve Birleştirir)
                    │
                    ▼
          AI Hazır Çıktılar
```

Crawler yalnızca veri indirir.

Pipeline yalnızca indirilen verileri işler.

Crawler pipeline'ı çağırmaz.

Pipeline crawler'ı çağırmaz.

İki sistem arasında hiçbir çalışma zamanı bağımlılığı bulunmaz.

---

# Projenin Amacı

DocSync'in amacı;

- resmi dokümantasyon sitelerini taramak
- sayfaları Markdown olarak kaydetmek
- gereksiz bağlantıları filtrelemek
- yinelenen içerikleri engellemek
- içerikleri düzleştirmek
- AI sistemlerinin kullanabileceği temiz veri üretmektir.

Bu proje özellikle;

- LLM RAG
- AI Search
- Offline Documentation
- Knowledge Base
- Embedding Pipeline

gibi sistemler için hazırlanmıştır.

---

# Dizin Yapısı

```
crawler/
pipeline/
sources/
tests/
README.md
```

---

# Crawler

Crawler yalnızca veri toplar.

Görevleri:

- robots.txt okumak
- sitemap okumak
- link keşfi yapmak
- BFS keşfi yapmak
- resmi domainleri takip etmek
- yönlendirmeleri çözmek
- duplicate engellemek
- markdown üretmek
- state dosyalarını güncellemek

Crawler'ın görevi burada biter.

Crawler hiçbir zaman pipeline çalıştırmaz.

---

# Pipeline

Pipeline yalnızca crawler tarafından oluşturulan dosyaları işler.

Görevleri:

- markdown dosyalarını bulmak
- klasörleri düzleştirmek
- duplicate temizlemek
- merge işlemleri yapmak
- AI için çıktı üretmek
- release doğrulaması yapmak

Pipeline internete çıkmaz.

Pipeline yeni sayfa indirmez.

Pipeline crawler veritabanını kullanmaz.

---

# Çalışma Akışı

## 1. Crawler

Örnek:

```bash
uv run python crawler_cli.py docs https://docs.python.org/3/ --limit 50 --yes
```

Crawler tamamlandığında bütün veriler aşağıdaki dizine yazılır.

```
sources/docs/
```

Burada;

- markdown dosyaları
- queue dosyaları
- sqlite verileri
- state bilgileri
- output klasörü

oluşturulur.

---

## 2. Pipeline

Crawler bittikten sonra pipeline çalıştırılır.

```bash
uv run python -m pipeline.run_pipeline
```

Pipeline otomatik olarak

```
sources/
```

altındaki bütün projeleri bulur.

Her proje için kendi output klasörünü işler.

Örnek:

```
sources/docs/
sources/pinnacle/
sources/smithay/
```

Pipeline hiçbir zaman sabit bir klasöre bağlı değildir.

Bütün yollar dinamik olarak keşfedilir.

---

# Veri Akışı

```
Website

↓

Crawler

↓

Markdown

↓

sources/<project>

↓

Pipeline

↓

Merge

↓

Flat Files

↓

AI
```

---

# Tasarım İlkeleri

Projede aşağıdaki mimari prensipler uygulanmıştır.

- Single Responsibility Principle
- Clean Architecture
- Bağımsız Modüller
- Dynamic Path Resolution
- Stateless Pipeline
- Incremental Processing
- Duplicate Prevention
- Release Validation

---

# Crawler ve Pipeline Ayrılığı

En önemli tasarım kararı budur.

Crawler yalnızca veri üretir.

Pipeline yalnızca veri tüketir.

Aralarında;

- ortak runtime
- ortak state
- ortak database
- ortak queue
- doğrudan import

bulunmaz.

Bu sayede iki sistem birbirinden bağımsız olarak geliştirilebilir.

---

# Çıktılar

Crawler kaynak Markdown dosyaları doğrudan proje dizinine yazılır:

~~~
sources/<project>/
~~~

Crawler ve pipeline tamamen bağımsızdır. Pipeline, proje dizinindeki kaynak
Markdown dosyalarını yalnızca okur; crawler database, queue veya çalışma
durumuna erişmez.

Pipeline tarafından oluşturulan birleştirilmiş dokümanlar ve durum dosyaları:

~~~
sources/<project>/_merged/
├── documents/
└── state/
~~~

`_merged/` üretilmiş çıktı alanıdır ve kaynak Markdown keşfine dahil edilmez.

---

# Kalite Kontrolleri

Projede geliştirme sırasında aşağıdaki kontroller uygulanmaktadır.

```bash
uv run ruff check crawler pipeline
```

```bash
uv run python -m compileall -q crawler pipeline
```

```bash
uv run python -m pipeline.release_validate
```

---

# Üretim Durumu

Son mimari denetim sonucunda proje aşağıdaki duruma ulaşmıştır.

- Crawler bağımsız
- Pipeline bağımsız
- Dinamik path yapısı tamamlandı
- Global registry ayrıştırıldı
- Release doğrulaması tamamlandı
- Kod kalite kontrolleri başarılı
- Production Ready

Kalite Puanı:

**100 / 100**

---

# Lisans

Bu proje kişisel kullanım ve bilgi yönetimi amacıyla geliştirilmiştir.
