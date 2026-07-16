import os
import pytest
from coding_agent.tools.web_search import WebSearch

class TestWebSearch:
    def setup_method(self):
        self.api_key = os.getenv('API_KEY')  # Set your test API key in environment variable
        self.search_engine_id = os.getenv('SEARCH_ENGINE_ID')  # Set your test search engine ID in environment variable
        self.web_search = WebSearch(self.api_key, self.search_engine_id)

    def test_search_results(self):
        results = self.web_search.search('OpenAI')
        assert len(results) > 0
        assert 'title' in results[0]
        assert 'link' in results[0]

    def test_no_results(self):
        results = self.web_search.search('nonexistentkeyword123')
        assert results == []