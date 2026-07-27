## Crawler Özellikleri

### Komut Satırı ve Yapılandırma

* URL, kaynak dosyası veya proje hedefi üzerinden crawler çalıştırma
* Komut satırı argümanlarını doğrulama ve tipli çalışma ayarlarına dönüştürme
* Başlangıç URL’sinden otomatik proje, workspace ve çıktı yolu oluşturma
* Her kaynak için bağımsız SQLite veritabanı, Markdown dizini ve log dizini üretme
* Maksimum sayfa, kuyruk boyutu, tarama derinliği ve batch boyutu sınırları
* Batch işlemleri arasında yapılandırılabilir bekleme süresi
* Minimum ve maksimum istek gecikmesiyle hız sınırlama
* Taramanın kuyruk tamamlanana kadar otomatik devam etmesi
* Tek seferlik veya recursive discovery destekli çalışma
* Daha önce tamamlanan taramaları algılayarak güncelleme kontrolü yapma

### Akıllı URL Keşfi

* Başlangıç URL’sinden recursive breadth-first search ile bağlantı keşfi
* HTML bağlantılarından gerçek ve taranabilir URL’leri çıkarma
* Relative URL’leri doğru ana URL ile birleştirme
* `robots.txt` içindeki sitemap adreslerini keşfetme
* XML sitemap ve sitemap index dosyalarını işleme
* Certificate Transparency kayıtlarından resmî alt alan adlarını keşfetme
* Aynı siteye veya resmî host ailesine ait URL’leri takip etme
* Keşfedilen URL’leri önem ve uygunluk puanına göre sıralama
* Değerli dokümantasyon köklerini otomatik yükseltme
* Dinamik path kapsamı belirleme
* Ortak URL path prefix’lerini çıkarma
* Kaynak dalları ve resmî dokümantasyon bölümlerini tespit etme
* Maksimum keşif sayfası ve derinlik sınırı uygulama
* Keşif sonuçlarını accepted, blocked ve review gruplarına ayırma
* Keşif durumunu ayrı SQLite veritabanında kalıcı tutma
* Daha önce görülen keşif URL’lerini tekrar işlememe

### URL Normalizasyonu ve Filtreleme

* URL şeması, host, port, path, fragment ve query bileşenlerini normalize etme
* Takip parametrelerini ve gereksiz query değerlerini kaldırma
* Canonical URL eşleştirmesi
* Redirect hedeflerini normalize etme
* Aynı URL’nin farklı yazımlarını tek kimlik altında birleştirme
* Bozuk, geçersiz veya desteklenmeyen URL’leri engelleme
* Makine dosyaları, medya dosyaları ve taranamayan içerik türlerini filtreleme
* Sosyal medya, yardımcı servis ve ilgisiz haricî hostları engelleme
* Bölgesel veya dil belirten URL segmentlerini tespit etme
* İngilizce olmayan host, path ve query varyasyonlarını filtreleme
* Aynı siteye ait bölgesel kopyaları engelleme
* İzin verilen path kapsamı dışındaki URL’leri reddetme
* Hard blacklist kuralları uygulama
* URL’nin hangi proje veya workspace’e ait olduğunu belirleme
* Projeler arasında aynı URL’nin birden fazla sahiplenilmesini önleme

### HTTP İndirme

* Asenkron HTTP istekleri
* İndirme öncesi URL, içerik türü ve dil kapıları
* HTTP response metadata inceleme
* Redirect zinciri takibi
* Final URL kaydı
* Timeout ve bağlantı hatası yönetimi
* Robots politikası kontrolü
* `crawl-delay` desteği
* Saygılı ve yapılandırılabilir istek gecikmesi
* HTML olmayan içeriklerin indirme öncesinde reddedilmesi
* Gerekli durumlarda dinamik HTML için tarayıcı tabanlı fallback kararı
* Boş veya yetersiz response’ların yeniden indirme politikası
* İstek ve host bazlı çalışma istatistikleri

### Dil Kontrolü

* URL üzerinden açık dil veya bölge sinyallerini algılama
* HTML `lang` özniteliğini değerlendirme
* `meta` dil ve locale etiketlerini kontrol etme
* İçerik örneğinden İngilizce uygunluğunu belirleme
* Güvenilir biçimde İngilizce olmayan sayfaları engelleme
* Sitemap URL’lerine özel dil filtresi
* Nötr veya İngilizce içeriği kabul etme
* Dil reddetme nedenlerini raporlama

### İçerik Ayrıştırma

* HTML içeriğini ayrıştırma
* Ana dokümantasyon içeriğini çıkarma
* Sayfa başlığı ve metadata bilgilerini toplama
* Canonical URL bilgisini okuma
* Linkleri normalize etme
* HTML içeriğini temiz Markdown biçimine dönüştürme
* Gereksiz navigasyon, sayfa kabuğu ve yardımcı öğeleri temizleme
* Kaynak URL bilgisini çıktı dosyalarında koruma
* Ayrıştırılmış sonucu tipli veri modeli olarak taşıma

### Sayfa Kalitesi

* HTML ve Markdown çıktı kalitesini değerlendirme
* Boş veya anlamsız sayfaları tespit etme
* Yetersiz içerikli sayfaları reddetme veya yeniden indirmeye alma
* Dokümantasyon niteliği taşımayan sayfaları filtreleme
* İçerik uzunluğu ve kullanılabilirlik kontrolleri
* Kalite kararlarının crawler durumuna yansıtılması

### Tekilleştirme

* Normalize edilmiş URL üzerinden tekrar tespiti
* Final URL üzerinden tekrar tespiti
* Canonical URL üzerinden tekrar tespiti
* Redirect hedefi üzerinden tekrar tespiti
* İçerik hash’i üzerinden birebir içerik tekrarını tespit etme
* Proje genelinde kalıcı URL sahipliği kontrolü
* Aynı içeriğin farklı URL’lerden tekrar yazılmasını önleme
* Tekrar nedenlerini çalışma özetinde gösterme

Crawler tamamlandıktan sonraki çalıştırmalarda değişen sayfaları günceller, eksik Markdown dosyalarını yeniden oluşturur ve URL, final URL, canonical URL, redirect hedefi veya içerik hash’i üzerinden bulunan tekrarları atlar.

### Kalıcı Kuyruk ve SQLite Durumu

* URL kuyruğunu SQLite içinde kalıcı tutma
* `pending`, `processing`, `done` ve `error` durumları
* İşlem sırasında yarım kalan kayıtları tekrar `pending` durumuna alma
* Tamamlanmış taramaları algılama
* Eksik Markdown çıktısı bulunan kayıtları yeniden kuyruğa alma
* Her sayfa için HTTP, canonical, hash ve çıktı bilgilerini saklama
* Batch bazlı kuyruk yürütme
* Kuyruk tamamlanana kadar otomatik batch devamı
* Maksimum kuyruk boyutu kontrolü
* Tarama yeniden başlatıldığında mevcut durumdan devam etme
* SQLite kilitlenmelerinde retry ve rollback yönetimi
* Keşif veritabanı ile crawler veritabanını birbirinden ayırma

### Markdown Çıktıları

* Her indirilen sayfayı bağımsız Markdown dosyası olarak yazma
* Deterministik ve güvenli dosya adı oluşturma
* Kaynak dizin yapısını koruma
* Eksik Markdown dosyalarını otomatik geri yükleme
* Değişen sayfaların mevcut çıktılarını güncelleme
* Kaynak manifesti oluşturma
* Manifest değişiklik geçmişini append-only Markdown dosyasında saklama
* Workspace ve kaynak bazlı çıktı organizasyonu

### Robots ve Sitemap Desteği

* `robots.txt` indirme ve ayrıştırma
* User-agent izinlerini kontrol etme
* Disallow kurallarını uygulama
* Robots içindeki sitemap bildirimlerini çıkarma
* Robots `crawl-delay` değerini kullanma
* Sitemap XML dosyalarını ayrıştırma
* Sitemap index dosyalarını recursive işleme
* Sitemap URL’lerini normalize etme
* Sitemap kapsamı ve dil filtresi uygulama
* Hatalı veya erişilemeyen sitemap kaynaklarını güvenli biçimde atlama

### Politika ve Kapsam Motoru

* URL, canonical URL ve host kapsamı için merkezi politika kararları
* Aynı domain, alt domain ve resmî host ilişkilerini değerlendirme
* Resmî host grafiğini kalıcı olarak saklama
* URL amacını dokümantasyon, kaynak, yardımcı veya ilgisiz olarak sınıflandırma
* Yüksek değerli dokümantasyon path’lerini önceliklendirme
* Path kapsamı dışına çıkan bağlantıları engelleme
* Discovery ve normal crawler aşamalarında ortak URL politikaları kullanma
* Kabul, atlama, engelleme ve inceleme nedenlerini açık biçimde üretme

### Çalışma Alanı Yönetimi

* Keşif sonuçlarından otomatik workspace oluşturma
* Accepted, blocked ve review sonuçlarını ayrı gruplama
* Seed dosyaları oluşturma
* Kaynak manifest yollarını merkezi biçimde yönetme
* Workspace, state, sources ve logs dizinlerini birbirinden ayırma
* URL’leri host ve path yapısına göre düzenleme
* İnsan incelemesi gereken sonuçlar için review kuyruğu üretme
* Deterministik proje ve kaynak isimleri oluşturma

### Terminal Arayüzü

* Tek ve kalıcı Rich Live terminal paneli
* İndirilen, güncellenen, atlanan, tekrar bulunan ve hatalı URL sayaçları
* Kuyruk durumlarının canlı gösterimi
* Aktif URL ve host bilgisinin gösterimi
* Batch ilerleme bilgisi
* Sitemap ve seed sayıları
* Recursive discovery durumu
* Maksimum sayfa, derinlik ve kuyruk limitlerinin gösterimi
* Tahmini batch sayısı
* Başlangıç ve final çalışma özeti
* Çıktı, veritabanı ve log yollarının gösterimi
* Tamamlanma durumunun açık şekilde bildirilmesi

Gerçek çalışma çıktısı tek bir kalıcı Rich Live dashboard kullanıldığını, kuyruk sayaçlarını, rate limit değerlerini, allowed path’i ve otomatik devam ayarlarını gösterir.

### Gözlemlenebilirlik ve Raporlama

* Çalışma boyunca crawler olaylarını sayma
* Host bazlı istatistik toplama
* İndirme, güncelleme, tekrar, atlama ve hata nedenlerini kaydetme
* Markdown gözlemlenebilirlik raporu üretme
* JSON gözlemlenebilirlik raporu üretme
* Her çalışma için zaman damgalı log dizini
* Ayrıntılı `crawler.log` dosyası
* Final kuyruk ve çalışma özeti
* Tamamlanan, bekleyen, işlenen ve hatalı kayıt sayılarını raporlama
* Çıktı dizini, SQLite dosyası ve log yolunu raporlama

Denetlenen koşuda Markdown ve JSON gözlemlenebilirlik raporları ayrı dosyalar olarak oluşturulmuştur.

### Güvenilirlik ve Kurtarma

* Kesintiye uğramış `processing` kayıtlarını otomatik kurtarma
* Daha önce tamamlanan taramaları güvenli biçimde yeniden kontrol etme
* Değişen sayfaları güncelleme
* Eksik çıktı dosyalarını yeniden üretme
* Aynı sayfayı farklı URL kimlikleriyle tekrar indirmeme
* SQLite yazma işlemlerinde kilitlenme retry mekanizması
* Ağ, parse ve kalite hatalarını kuyruk durumuna kaydetme
* Kuyrukta iş kalmadığında kesin tamamlanma durumu üretme
* Kontrollü batch çalıştırma
* Sınırsız veya yapılandırılmış maksimum batch sayısı

### Geliştirme Kalitesi

* Tüm Python dosyaları için otomatik syntax compilation kontrolü
* Ruff lint kontrolü
* Ruff format kontrolü
* BasedPyright tip kontrolü
* Strict mypy kontrolü
* Kalıcı preflight raporu
* Crawler başlamadan proje genelinde doğrulama
* Tipli runtime context ve veri modelleri
* Ağ, persistence, parsing, policy, discovery ve terminal sorumluluklarının ayrı modüllerde tutulması

Denetim çalışmasında Python compilation, Ruff lint, Ruff format, BasedPyright ve strict mypy kontrolleri başarıyla geçmiştir.

