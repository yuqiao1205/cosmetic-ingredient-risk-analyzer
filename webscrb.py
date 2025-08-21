import os
import click
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException

@click.command()
@click.argument('url')
@click.option('--type', 'render_type', default='html', help='Render type: html or pdf (default: html)')
@click.option('--output', '-o', help='Output file path (optional, prints to terminal if not specified)')
@click.option('--wait', default=10, help='Wait time in seconds for page to load (default: 10)')
@click.option('--headless', is_flag=True, help='Run browser in headless mode')
def main(url, render_type, output, wait, headless):
    """Convert a URL to HTML or PDF using Selenium with local browser."""
    
    # Setup Chrome options
    chrome_options = Options()
    if headless:
        chrome_options.add_argument("--headless")
    chrome_options.add_argument("--no-sandbox")
    chrome_options.add_argument("--disable-dev-shm-usage")
    chrome_options.add_argument("--disable-gpu")
    chrome_options.add_argument("--window-size=1920,1080")
    
    # Add realistic user agent
    chrome_options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    
    driver = None
    try:
        driver = webdriver.Chrome(options=chrome_options)
        driver.set_page_load_timeout(wait)
        
        click.echo(f"Loading {url}...")
        driver.get(url)
        
        # Wait for page to be ready
        WebDriverWait(driver, wait).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        
        if render_type == 'html':
            # Get page source
            html_content = driver.page_source
            
            if output:
                with open(output, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                click.echo(f"HTML saved to {output}")
            else:
                click.echo(html_content)
                
        elif render_type == 'pdf':
            # Print to PDF (Chrome's built-in PDF printing)
            if output:
                driver.execute_script("window.print();")
                click.echo(f"PDF print dialog opened - save to {output}")
            else:
                click.echo("PDF print dialog opened")
                
    except TimeoutException:
        click.echo(f"Timeout: Page took longer than {wait} seconds to load", err=True)
    except WebDriverException as e:
        click.echo(f"WebDriver error: {e}", err=True)
    except Exception as e:
        click.echo(f"Unexpected error: {e}", err=True)
    finally:
        if driver:
            driver.quit()
