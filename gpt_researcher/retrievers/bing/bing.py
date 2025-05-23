# Bing Search Retriever

# libraries
import os
import requests
import json
import logging


class BingSearch():
    """
    Bing Search Retriever
    """

    def __init__(self, query, query_domains=None):
        """
        Initializes the BingSearch object
        Args:
            query:
        """
        self.query = query
        self.query_domains = query_domains or None
        self.api_key = self.get_api_key()
        self.logger = logging.getLogger(__name__)

    def get_api_key(self):
        """
        Gets the Bing API key
        Returns:

        """
        try:
            api_key = os.environ["BING_API_KEY"]
        except:
            raise Exception(
                "Bing API key not found. Please set the BING_API_KEY environment variable.")
        return api_key

    def search(self, max_results=7) -> list[dict[str]]:
        """
        Searches the query and tries to return at least max_results filtered links.
        Performs additional Bing API requests with offset if not enough valid links found.
        """
        print("Searching with query {0}...".format(self.query))
        url = "https://api.bing.microsoft.com/v7.0/search"
        headers = {
            'Ocp-Apim-Subscription-Key': self.api_key,
            'Content-Type': 'application/json'
        }
        filtered_results = []
        seen_urls = set()
        dropped_dead = 0
        dropped_domain = 0
        offset = 0
        page_size = max_results  # Bing API max 50, но обычно достаточно max_results
        max_attempts = 5  # ограничим число дозапросов, чтобы не уйти в бесконечный цикл
        attempts = 0
        while len(filtered_results) < max_results and attempts < max_attempts:
            params = {
                "responseFilter": "Webpages",
                "q": self.query,
                "count": page_size,
                "offset": offset,
                "setLang": "en-GB",
                "textDecorations": False,
                "textFormat": "HTML",
                "safeSearch": "Strict"
            }
            resp = requests.get(url, headers=headers, params=params)
            if resp is None:
                break
            try:
                search_results = json.loads(resp.text)
                results = search_results["webPages"]["value"]
            except Exception as e:
                self.logger.error(
                    f"Error parsing Bing search results: {e}. Resulting in empty response.")
                break
            if not results:
                break
            for result in results:
                url_ = result["url"]
                # skip youtube results
                if "youtube.com" in url_:
                    continue
                # filter by domain if query_domains is set
                if self.query_domains:
                    allowed = False
                    for domain in self.query_domains:
                        if domain.lower() in url_.lower():
                            allowed = True
                            break
                    if not allowed:
                        dropped_domain += 1
                        continue
                # skip duplicates
                if url_ in seen_urls:
                    continue
                seen_urls.add(url_)
                # check if link is alive (HEAD request, 3s timeout)
                try:
                    if url_.startswith("http"):
                        r = requests.head(url_, timeout=3, allow_redirects=True)
                        if r.status_code >= 400:
                            dropped_dead += 1
                            continue
                except Exception:
                    dropped_dead += 1
                    continue
                search_result = {
                    "title": result["name"],
                    "href": url_,
                    "body": result["snippet"],
                }
                filtered_results.append(search_result)
                if len(filtered_results) >= max_results:
                    break
            offset += page_size
            attempts += 1
        self.logger.info(f"Bing retriever: {dropped_dead} dead links dropped, {dropped_domain} domain-filtered, {len(filtered_results)} results returned.")
        return filtered_results[:max_results]
