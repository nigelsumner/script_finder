# Script Finder

A Python application to find and download PDF movie/TV scripts from websites with minimal user intervention.

## Features

- **Simple UI** - Enter any website URL to scan for PDF scripts
- **Smart Detection** - Automatically identifies PDF links related to scripts, screenplays, and teleplays
- **Follow Links** - Optionally follows links on the page to find PDFs on linked pages
- **Filtering** - Filter results by keyword (e.g., "pilot", "screenplay")
- **Batch Download** - Download all found scripts or select specific ones
- **Auto-Download** - Option to automatically download all found scripts
- **Progress Tracking** - See download status for each file

## Installation

1. Make sure you have Python 3.8+ installed

2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Usage

1. Run the application:
   ```bash
   python script_finder.py
   ```

2. Enter a website URL that contains script PDFs (e.g., a script database or archive)

3. Optionally set:
   - **Download Directory** - Where to save the scripts (default: ~/Downloads/Scripts)
   - **Follow Links** - Check to scan linked pages for more PDFs
   - **Auto-Download** - Automatically download all found scripts
   - **Filter** - Enter keywords to filter results

4. Click "Scan for Scripts" to search the page

5. Review found scripts and either:
   - Select specific scripts and click "Download Selected"
   - Click "Download All" to get everything

## Popular Script Sources

Some websites known to host movie/TV scripts:
- Script archives and databases
- Film studio press sites
- Educational resources
- Film analysis websites

## Notes

- The application respects website rate limits and uses reasonable timeouts
- Some websites may block automated requests
- PDF files are saved with their original filenames when possible
- Duplicate filenames are handled by adding a number suffix

## Requirements

- Python 3.8+
- requests
- beautifulsoup4
- lxml
- tkinter (usually included with Python)
