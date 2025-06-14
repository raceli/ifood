"""
File: tools/ifood_scraper.py
Date: 2024-07-31
Description: A web scraper for iFood restaurant pages to extract dish information using scrapegraphai and Gemini.
"""

import os
import json
from scrapegraphai.graphs import SmartScraperGraph
from scrapegraphai.utils import prettify_exec_info
from dotenv import load_dotenv
import logging

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()

def scrape_ifood_menu(url: str):
    """
    Scrapes an iFood restaurant menu to extract dish names, descriptions, and images.

    Args:
        url (str): The URL of the iFood restaurant page.

    Returns:
        dict: The scraped data in JSON format, or None if an error occurs.
    """
    gemini_api_key = os.getenv("GEMINI_API_KEY")
    if not gemini_api_key:
        logger.error("GEMINI_API_KEY not found in environment variables. Please set it in a .env file.")
        raise ValueError("GEMINI_API_KEY not found in environment variables.")

    graph_config = {
        "llm": {
            "model": "google_genai/gemini-2.0-flash",
            "api_key": gemini_api_key,
            "temperature": 0,
            "model_tokens": 1048576,
        },
        "verbose": True,
        "scraper": {
            "headless": True, # Set to False if you want to see the browser actions
        }
    }

    prompt = """
    Please extract the following information for every dish from the menu on the page.
    For each dish, provide:
    - name: The name of the dish.
    - description: The detailed description of the dish.
    - image_url: The URL of the dish's image.
    
    The output should be a JSON array of objects, where each object represents a dish.
    Example of a single dish object:
    {
        "name": "Whopper",
        "description": "A classic burger with a flame-grilled beef patty, fresh lettuce, ripe tomatoes, onions, pickles, and creamy mayonnaise, all on a toasted sesame seed bun.",
        "image_url": "https://example.com/images/whopper.jpg"
    }
    """

    smart_scraper_graph = SmartScraperGraph(
        prompt=prompt,
        source=url,
        config=graph_config
    )

    try:
        logger.info(f"Starting to scrape URL: {url}")
        result = smart_scraper_graph.run()
        logger.info("Scraping finished successfully.")
        
        # Log execution info for debugging
        graph_exec_info = smart_scraper_graph.get_execution_info()
        logger.debug(prettify_exec_info(graph_exec_info))

        return result

    except Exception as e:
        logger.error(f"An error occurred during scraping: {e}", exc_info=True)
        return None

if __name__ == '__main__':
    # The iFood URL to scrape
    ifood_url = "https://www.ifood.com.br/delivery/sao-paulo-sp/bologna-padaria-restaurante-e-rotisseria-consolacao/19cf4c5b-b50d-4472-9bd2-3ca177759d63"
    
    scraped_data = scrape_ifood_menu(ifood_url)
    
    if scraped_data:
        # Save to a file
        output_filename = "ifood_menu.json"
        with open(output_filename, 'w', encoding='utf-8') as f:
            json.dump(scraped_data, f, ensure_ascii=False, indent=4)
        logger.info(f"Scraped data saved to {output_filename}")
        
        # Print to console
        # print(json.dumps(scraped_data, indent=4)) 