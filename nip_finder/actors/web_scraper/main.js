/**
 * Apify Actor - NIP Finder Web Scraper
 * Scrapuje liste URL i wyciaga tekst. Uzywa Playwright dla JS.
 */

const { Actor } = require('apify');
const { chromium } = require('playwright');

Actor.main(async () => {
    const input = await Actor.getInput();
    
    if (!input || !input.urls || !Array.isArray(input.urls)) {
        throw new Error('Input musi zawierac tablice "urls"');
    }
    
    const urls = input.urls;
    const maxTextLength = input.maxTextLength || 10000;
    const timeout = input.timeout || 30000;
    
    console.log(`Scraping ${urls.length} URL (max text: ${maxTextLength} chars)`);
    
    const browser = await chromium.launch({
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox']
    });
    
    const results = [];
    
    for (const url of urls) {
        console.log(`Scraping: ${url}`);
        const page = await browser.newPage();
        
        try {
            await page.goto(url, { waitUntil: 'networkidle', timeout });
            
            // Wyciagnij tekst - priorytet: footer, sekcje kontakt/nip, cala strona
            const extractedData = await page.evaluate((maxLen) => {
                function cleanText(element) {
                    if (!element) return '';
                    const unwanted = element.querySelectorAll('script, style, nav, header, aside, iframe');
                    unwanted.forEach(el => el.remove());
                    return element.innerText || element.textContent || '';
                }
                
                // PRIORYTET 1: Footer
                const footer = document.querySelector('footer');
                if (footer) {
                    const footerText = cleanText(footer);
                    if (footerText.length > 100) {
                        return { text: footerText.substring(0, maxLen), source: 'footer' };
                    }
                }
                
                // PRIORYTET 2: Sekcje z NIP/kontakt
                const keywords = ['nip', 'kontakt', 'rodo', 'polityka', 'administrator'];
                const sections = document.querySelectorAll('section, div[class*="contact"], div[class*="footer"]');
                
                for (const section of sections) {
                    const text = cleanText(section);
                    if (keywords.some(kw => text.toLowerCase().includes(kw)) && text.length > 100) {
                        return { text: text.substring(0, maxLen), source: 'relevant_section' };
                    }
                }
                
                // PRIORYTET 3: Cala strona
                return { text: cleanText(document.body).substring(0, maxLen), source: 'full_page' };
                
            }, maxTextLength);
            
            results.push({
                url: url,
                text: extractedData.text,
                textSource: extractedData.source,
                success: true,
                textLength: extractedData.text.length,
            });
            
            console.log(`OK: ${extractedData.text.length} chars from ${extractedData.source}`);
            
        } catch (error) {
            console.error(`Error scraping ${url}: ${error.message}`);
            results.push({
                url: url,
                text: '',
                success: false,
                error: error.message,
            });
        } finally {
            await page.close();
        }
    }
    
    await browser.close();
    console.log(`Completed: ${results.filter(r => r.success).length}/${results.length} successful`);
    
    await Actor.pushData(results);
});
