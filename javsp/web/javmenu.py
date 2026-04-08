"""从JavMenu抓取数据"""
import logging

from javsp.web.base import Request, resp2html
from javsp.web.exceptions import *
from javsp.datatype import MovieInfo


request = Request()

logger = logging.getLogger(__name__)
base_url = 'https://mrzyx.xyz'


def _first(ls):
    return ls[0] if ls else None


def parse_data(movie: MovieInfo):
    """从网页抓取并解析指定番号的数据
    Args:
        movie (MovieInfo): 要解析的影片信息，解析后的信息直接更新到此变量内
    """
    # JavMenu网页做得很不走心，将就了
    url = f'{base_url}/{movie.dvdid}'
    r = request.get(url, delay_raise=True)
    if r.status_code == 404:
        raise MovieNotFoundError(__name__, movie.dvdid)
    if r.status_code in (403, 429, 503):
        raise SiteBlocked(f'JavMenu: HTTP {r.status_code}，可能触发反爬或被站点限制')
    if r.status_code >= 400:
        raise WebsiteError(f'JavMenu: 非预期状态码 {r.status_code}: {url}')
    if r.history:
        # 被重定向到主页说明找不到影片资源
        raise MovieNotFoundError(__name__, movie.dvdid)

    html = resp2html(r)
    # 新版容器class从'col-md-9 px-0'调整为'col-md-9 px-1 px-md-0'
    container = _first(html.xpath("//div[@class='col-md-9 px-0']"))
    if container is None:
        container = _first(html.xpath("//div[contains(@class,'col-md-9') and contains(@class,'px-1')]"))
    if container is None:
        raise MovieNotFoundError(__name__, movie.dvdid)

    title_raw = container.xpath(".//div[contains(@class,'mb-3')]/h1//text()")
    title = ' '.join([i.strip() for i in title_raw if i.strip()])
    if not title:
        # 部分非详情页会直接落到推荐页（title通常是"猜你喜歡"）
        raise MovieNotFoundError(__name__, movie.dvdid)
    # 竟然还在标题里插广告，真的疯了。要不是我已经写了抓取器，才懒得维护这个破站
    title = title.replace('  | JAV目錄大全 | 每日更新', '')
    title = title.replace(' 免費在線看', '').replace(' 免費AV在線看', '')
    cover_tag = container.xpath(".//div[@class='single-video']")
    if len(cover_tag) > 0:
        video_tag = cover_tag[0].find('video')
        if video_tag is not None and video_tag.get('data-poster'):
            # URL首尾竟然也有空格……
            movie.cover = video_tag.get('data-poster').strip()
        if not movie.cover:
            cover_img = _first(cover_tag[0].xpath(".//img/@src"))
            if cover_img:
                movie.cover = cover_img.strip()
        # 预览影片改为blob了，无法获取
        # movie.preview_video = video_tag.find('source').get('src').strip()
    if not movie.cover:
        cover_img_tag = container.xpath(".//img[contains(@class,'lazy') and contains(@class,'rounded')]/@data-src")
        if cover_img_tag:
            movie.cover = cover_img_tag[0].strip()
    info = _first(container.xpath(".//div[contains(@class,'card-body')]"))
    if info is None:
        raise MovieNotFoundError(__name__, movie.dvdid)

    publish_date = _first(info.xpath(".//span[contains(text(), '發佈於:')]/following-sibling::span[1]/text()"))
    duration = _first(info.xpath(".//span[contains(text(), '時長:')]/following-sibling::span[1]/text()"))
    if duration:
        duration = duration.replace('分鐘', '').strip()
    producer = _first(info.xpath(".//span[contains(text(), '製作:')]/following-sibling::a[1]/span/text()"))
    if producer:
        movie.producer = producer

    # 新版把番号拆成两段（如FC2 和 -718323）
    dvd_head = _first(info.xpath(".//span[contains(text(), '番號:')]/following-sibling::span[1]/text()"))
    dvd_tail = _first(info.xpath(".//span[contains(text(), '番號:')]/following-sibling::span[2]/text()"))
    if dvd_head and dvd_tail:
        movie.dvdid = (dvd_head + dvd_tail).replace(' ', '')

    genre_tags = info.xpath(".//a[@class='genre']")
    genre, genre_id = [], []
    for tag in genre_tags:
        items = tag.get('href').split('/')
        if len(items) >= 3:
            pre_id = items[-3] + '/' + items[-1]
        else:
            pre_id = tag.get('href')
        genre.append(tag.text.strip())
        genre_id.append(pre_id)
        # genre的链接中含有censored字段，但是无法用来判断影片是否有码，因为完全不可靠……
    actress = info.xpath(".//span[contains(text(), '女優:')]/following-sibling::*//a/text()") or None
    magnet_table = container.xpath(".//table[contains(@class, 'magnet-table')]/tbody")
    if magnet_table:
        magnet_links = magnet_table[0].xpath("tr/td/a/@href")
        # 它的FC2数据是从JavDB抓的，JavDB更换图片服务器后它也跟上了，似乎数据更新频率还可以
        movie.magnet = [i.replace('[javdb.com]','') for i in magnet_links]
    preview_pics = container.xpath(".//a[@data-fancybox='gallery']/@href")

    if (not movie.cover) and preview_pics:
        movie.cover = preview_pics[0]
    movie.url = url
    dvdid_to_strip = movie.dvdid or ''
    movie.title = title.replace(dvdid_to_strip, '').strip()
    movie.preview_pics = preview_pics
    movie.publish_date = publish_date
    movie.duration = duration
    movie.genre = genre
    movie.genre_id = genre_id
    movie.actress = actress


if __name__ == "__main__":
    import pretty_errors
    pretty_errors.configure(display_link=True)
    logger.root.handlers[1].level = logging.DEBUG

    movie = MovieInfo('FC2-718323')
    try:
        parse_data(movie)
        print(movie)
    except CrawlerError as e:
        logger.error(e, exc_info=1)
