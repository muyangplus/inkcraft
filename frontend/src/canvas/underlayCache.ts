/**
 * Bounded LRU texture cache for page backgrounds and PDF overlay underlays,
 * with negative caching for failed URLs and lifecycle cleanup after engine destroy.
 */
export class UnderlayImageCache {
  private imageCache = new Map<string, HTMLImageElement>();
  private loadingUrls = new Set<string>();
  private failedUrls = new Set<string>();
  private destroyed = false;

  get(url: string | null): HTMLImageElement | null {
    if (!url) return null;
    const img = this.imageCache.get(url);
    if (!img) return null;
    // Refresh LRU position
    this.imageCache.delete(url);
    this.imageCache.set(url, img);
    return img;
  }

  ensureLoaded(url: string, onLoad: () => void): void {
    if (
      this.destroyed ||
      this.imageCache.has(url) ||
      this.loadingUrls.has(url) ||
      this.failedUrls.has(url)
    ) {
      return;
    }

    this.loadingUrls.add(url);
    const img = new Image();
    img.crossOrigin = 'anonymous';

    img.onload = () => {
      this.loadingUrls.delete(url);
      if (this.destroyed) return;
      if (this.imageCache.size >= 24) {
        const oldestKey = this.imageCache.keys().next().value;
        if (oldestKey) this.imageCache.delete(oldestKey);
      }
      this.imageCache.set(url, img);
      onLoad();
    };

    img.onerror = () => {
      this.loadingUrls.delete(url);
      if (this.destroyed) return;
      if (this.failedUrls.size >= 64) {
        this.failedUrls.clear();
      }
      this.failedUrls.add(url);
    };

    img.src = url;
  }

  destroy(): void {
    this.destroyed = true;
    this.imageCache.clear();
    this.loadingUrls.clear();
    this.failedUrls.clear();
  }
}
