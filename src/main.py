import csv
import re
import logging
from urllib.parse import urljoin

import requests_cache
from bs4 import BeautifulSoup
from tqdm import tqdm

from configs import configure_argument_parser, configure_logging
from constants import BASE_DIR, EXPECTED_STATUS, MAIN_DOC_URL, PEP_URL
from outputs import control_output
from utils import find_tag, get_response
from exceptions import ResponseError, VersionsNotFoundError


def response_soup(session, new_url):
    response = get_response(session, new_url)
    if response is None:
        raise ResponseError(new_url)
    soup = BeautifulSoup(response.text, features='lxml')
    return soup


def whats_new(session):
    whats_new_url = urljoin(MAIN_DOC_URL, 'whatsnew/')
    soup = response_soup(session, whats_new_url)
    main_div = find_tag(soup, 'section', attrs={'id': 'what-s-new-in-python'})
    div_with_ul = find_tag(main_div, 'div', attrs={'class': 'toctree-wrapper'})
    sections_by_python = div_with_ul.find_all(
        'li', attrs={'class': 'toctree-l1'}
    )
    results = [('Ссылка на статью', 'Заголовок', 'Редактор, автор')]
    for section in tqdm(sections_by_python):
        version_a_tag = find_tag(section, 'a')
        href = version_a_tag['href']
        version_link = urljoin(whats_new_url, href)
        response = get_response(session, version_link)
        if response is None:
            continue
        soup = BeautifulSoup(response.text, features='lxml')
        h1 = find_tag(soup, 'h1')
        dl = find_tag(soup, 'dl')
        dl_text = dl.text.replace('\n', ' ')
        results.append(
            (version_link, h1.text, dl_text)
        )
    return results


def latest_versions(session):
    soup = response_soup(session, MAIN_DOC_URL)
    sidebar = soup.find('div', {'class': 'sphinxsidebarwrapper'})
    ul_tags = sidebar.find_all('ul')
    for ul in ul_tags:
        if 'All versions' in ul.text:
            a_tags = ul.find_all('a')
            break
    else:
        raise VersionsNotFoundError()
    results = [('Ссылка на документацию', 'Версия', 'Статус')]
    pattern = r'Python (?P<version>\d\.\d+) \((?P<status>.*)\)'
    for a_tag in a_tags:
        link = a_tag['href']
        text_match = re.search(pattern, a_tag.text)
        if text_match is not None:
            version, status = text_match.groups()
        else:
            version, status = a_tag.text, ''
        results.append(
            (link, version, status)
        )
    return results


def download(session):
    downloads_url = urljoin(MAIN_DOC_URL, 'download.html')
    soup = response_soup(session, downloads_url)
    main_tag = soup.find('div', {'role': 'main'})
    table_tag = main_tag.find('table', {'class': 'docutils'})
    pdf_a4_tag = table_tag.find('a', {'href': re.compile(r'.+pdf-a4\.zip$')})
    pdf_a4_link = pdf_a4_tag['href']
    archive_url = urljoin(downloads_url, pdf_a4_link)
    filename = archive_url.split('/')[-1]
    downloads_dir = BASE_DIR / 'downloads'
    downloads_dir.mkdir(exist_ok=True)
    archive_path = downloads_dir / filename
    response = session.get(archive_url)
    with open(archive_path, 'wb') as file:
        file.write(response.content)
    logging.info(f'Архив был загружен и сохранён: {archive_path}')


def get_pep_page_status(session, pep_link):
    response = get_response(session, pep_link)
    if response is None:
        return None
    soup = BeautifulSoup(response.text, 'lxml')
    status_tag = soup.find(string="Status").find_next('dd')
    if status_tag:
        return status_tag.text.strip()
    return None


def pep(session):
    soup = response_soup(session, PEP_URL)
    tables = soup.find_all('table')
    status_counts, total_peps, miss_statuses = process_pep_tables(
        tables, session
    )
    log_miss_statuses(miss_statuses)
    save_status_summary(status_counts, total_peps)
    return status_counts


def process_pep_tables(tables, session):
    status_counts = {}
    total_peps = 0
    miss_statuses = []
    for table in tables:
        rows = table.find_all('tr')[1:]
        for row in tqdm(rows):
            process_pep_row(row, session, status_counts, miss_statuses)
            total_peps += 1
    return status_counts, total_peps, miss_statuses


def process_pep_row(row, session, status_counts, miss_statuses):
    columns = row.find_all('td')
    if len(columns) < 3 or str(columns[0]) == '<td></td>':
        return
    link_element = find_tag(columns[1], 'a')
    expected_status = find_tag(columns[0], 'abbr')
    if not link_element or not expected_status:
        return
    pep_link = urljoin(PEP_URL, link_element['href'])
    actual_status = get_pep_page_status(session, pep_link)
    expected_status_title = expected_status['title'].split(", ")[1]
    if actual_status and actual_status != expected_status_title:
        miss_statuses.append({
            'link': pep_link,
            'actual_status': actual_status,
            'expected_status': expected_status_title
        })
    update_status_counts(actual_status, status_counts)


def update_status_counts(actual_status, status_counts):
    for key, statuses in EXPECTED_STATUS.items():
        if actual_status in statuses:
            status_counts[actual_status] = status_counts.get(
                actual_status, 0) + 1
            break


def log_miss_statuses(miss_statuses):
    if miss_statuses:
        logging.info('Несовпадающие статусы:')
        for status in miss_statuses:
            logging.info(
                f"{status['link']}\n"
                f"Статус в карточке: {status['actual_status']}\n"
                f"Ожидаемый статус: {status['expected_status']}"
            )


def save_status_summary(status_counts, total_peps):
    results_dir = BASE_DIR / 'results'
    results_dir.mkdir(exist_ok=True)
    with open(
        results_dir / 'pep_status.csv', 'w', newline='', encoding='utf-8'
    ) as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(['Статус', 'Количество'])
        for status, count in status_counts.items():
            writer.writerow([status, count])
        writer.writerow(['Total', total_peps])
    logging.info(f'Общее количество PEP: {total_peps}')
    for status, count in status_counts.items():
        logging.info(f'{status}: {count}')


MODE_TO_FUNCTION = {
    'whats-new': whats_new,
    'latest-versions': latest_versions,
    'download': download,
    'pep': pep,
}


def main():
    configure_logging()
    logging.info('Парсер запущен!')
    arg_parser = configure_argument_parser(MODE_TO_FUNCTION.keys())
    args = arg_parser.parse_args()
    logging.info(f'Аргументы командной строки: {args}')
    session = requests_cache.CachedSession()
    if args.clear_cache:
        session.cache.clear()
    parser_mode = args.mode
    results = MODE_TO_FUNCTION[parser_mode](session)
    if results is not None:
        control_output(results, args)
    logging.info('Парсер завершил работу.')


if __name__ == '__main__':
    main()
