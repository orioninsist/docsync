set shell := ["bash", "-cu"]

# ============================================================
# DOCSYNC
#
# Ana kullanım artık `docsync` komutu üzerindendir.
# Bu justfile sadece kısa yardım ekranı gösterir.
#
# ============================================================

default:
    @just help

help:
    @echo ""
    @echo "============================================================"
    @echo " DOCSYNC"
    @echo "============================================================"
    @echo ""
    @echo "DOCSYNC artık tek ana komut üzerinden kullanılmaktadır:"
    @echo ""
    @echo "  docsync"
    @echo ""
    @echo "KULLANIM"
    @echo ""
    @echo "  docsync docs <hedef>"
    @echo "      URL, .txt dosyası veya workspace için tüm süreci çalıştırır."
    @echo "      İş akışı: Crawl -> Flatten -> Incremental Update -> Merge"
    @echo ""
    @echo "  docsync release"
    @echo "      Commit veya release öncesi doğrulama kontrollerini çalıştırır."
    @echo ""
    @echo "  docsync clean"
    @echo "      __pycache__ ve *.pyc dosyalarını temizler."
    @echo ""
    @echo "ÖRNEKLER"
    @echo ""
    @echo "  docsync docs https://docs.python.org/3/"
    @echo "  docsync docs sites.txt"
    @echo "  docsync docs printify"
    @echo ""