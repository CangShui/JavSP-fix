"""从FC2官网抓取数据"""
import logging


from javsp.web.base import get_html, request_get, resp2html
from javsp.web.exceptions import *
from javsp.config import Cfg
from javsp.lib import strftime_to_minutes
from javsp.datatype import MovieInfo


logger = logging.getLogger(__name__)
base_url = 'https://adult.contents.fc2.com'


def _first(ls):
    return ls[0] if ls else None


def _abs_url(url: str | None):
    if not url:
        return None
    if url.startswith('//'):
        return 'https:' + url
    return url


def get_movie_score(fc2_id):
    """通过评论数据来计算FC2的影片评分（10分制），无法获得评分时返回None"""
    html = get_html(f'{base_url}/article/{fc2_id}/review')
    review_tags = html.xpath("//ul[@class='items_comment_headerReviewInArea']/li")
    reviews = {}
    for tag in review_tags:
        score = int(tag.xpath("div/span/text()")[0])
        vote = int(tag.xpath("span")[0].text_content())
        reviews[score] = vote
    total_votes = sum(reviews.values())
    if (total_votes >= 2):   # 至少也该有两个人评价才有参考意义一点吧
        summary = sum([k*v for k, v in reviews.items()])
        final_score = summary / total_votes * 2   # 乘以2转换为10分制
        return final_score


def parse_data(movie: MovieInfo):
    """解析指定番号的影片数据"""
    # 去除番号中的'FC2'字样
    id_uc = movie.dvdid.upper()
    if not id_uc.startswith('FC2-'):
        raise ValueError('Invalid FC2 number: ' + movie.dvdid)
    fc2_id = id_uc.replace('FC2-', '')
    # 抓取网页
    url = f'{base_url}/article/{fc2_id}/'
    resp = request_get(url, delay_raise=True)
    if resp.status_code == 404:
        raise MovieNotFoundError(__name__, movie.dvdid)
    if resp.status_code in (403, 429):
        raise SiteBlocked(f'FC2: HTTP {resp.status_code}，可能受地区限制或触发反爬')
    if resp.status_code >= 400:
        raise WebsiteError(f'FC2: 非预期状态码 {resp.status_code}: {url}')
    if '/id.fc2.com/' in resp.url:
        raise SiteBlocked('FC2要求当前IP登录账号才可访问，请尝试更换为日本IP')
    html = resp2html(resp)
    container = html.xpath("//div[@class='items_article_left']")
    if len(container) > 0:
        container = container[0]
    else:
        raise MovieNotFoundError(__name__, movie.dvdid)
    # FC2 标题增加反爬乱码，使用数组合并标题
    title_arr = container.xpath("//div[@class='items_article_headerInfo']/h3/text()")
    title = ''.join([i.strip() for i in title_arr if i.strip()])
    if not title:
        raise WebsiteError(f'FC2: 无法提取标题: {url}')

    thumb_tag = _first(container.xpath("//div[@class='items_article_MainitemThumb']"))
    if thumb_tag is None:
        raise WebsiteError(f'FC2: 页面结构已变化，缺少封面区域: {url}')

    thumb_pic = _first(thumb_tag.xpath("span/img/@src"))
    duration_str = _first(thumb_tag.xpath("span/p[@class='items_article_info']/text()"))
    # FC2没有制作商和发行商的区分，作为个人市场，影片页面的'by'更接近于制作商
    producer = _first(container.xpath("//li[text()='by ']/a/text()"))
    if not producer:
        producer = _first(container.xpath("//li[contains(normalize-space(.), 'by')]/a/text()"))
    genre = container.xpath("//a[@class='tag tagTag']/text()")
    date_str = _first(container.xpath("//div[@class='items_article_Releasedate']/p/text()"))
    if not date_str:
        # FC2近期页面结构调整，日期可能位于items_article_softDevice
        date_str = _first(container.xpath("//div[contains(@class,'items_article_softDevice')]/p/text()"))
    publish_date = None
    if date_str:
        import re
        match = re.search(r'(\d{4}/\d{2}/\d{2})', date_str)
        if match:
            publish_date = match.group(1).replace('/', '-')
    preview_pics = [_abs_url(i) for i in container.xpath("//ul[@data-feed='sample-images']/li/a/@href")]

    if Cfg().crawler.hardworking:
        # 通过评论数据来计算准确的评分
        try:
            score = get_movie_score(fc2_id)
            if score:
                movie.score = f'{score:.2f}'
        except Exception as e:
            logger.debug(f'FC2: 获取评分失败: {e}')
        # 预览视频是动态加载的，不在静态网页中
        desc_frame_url = _first(container.xpath("//section[@class='items_article_Contents']/iframe/@src"))
        if desc_frame_url:
            key = desc_frame_url.split('=')[-1]     # /widget/article/718323/description?ac=60fc08fa...
            api_url = f'{base_url}/api/v2/videos/{fc2_id}/sample?key={key}'
            try:
                r = request_get(api_url).json()
                movie.preview_video = r.get('path')
            except Exception as e:
                logger.debug(f'FC2: 获取预览视频失败: {e}')
    else:
        # 获取影片评分。影片页面的评分只能粗略到星级，且没有分数，要通过类名来判断，如'items_article_Star5'表示5星
        score_tag_attr = _first(container.xpath("//a[@class='items_article_Stars']/p/span/@class"))
        if score_tag_attr and score_tag_attr[-1].isdigit():
            score = int(score_tag_attr[-1]) * 2
            movie.score = f'{score:.2f}'

    movie.dvdid = id_uc
    movie.url = url
    movie.title = title
    movie.genre = genre
    movie.producer = producer
    if duration_str:
        try:
            movie.duration = str(strftime_to_minutes(duration_str))
        except ValueError:
            logger.debug(f"FC2: 无法解析时长字段: '{duration_str}'")
    movie.publish_date = publish_date
    movie.preview_pics = preview_pics
    # FC2的封面是220x220的，和正常封面尺寸、比例都差太多。如果有预览图片，则使用第一张预览图作为封面
    if movie.preview_pics:
        movie.cover = preview_pics[0]
    else:
        movie.cover = _abs_url(thumb_pic)


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
