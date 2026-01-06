#!/usr/bin/env python3
"""
Script Finder - A tool to find and download PDF movie/TV scripts from websites.
"""

import os
import re
import sys
import warnings
from urllib.parse import urljoin, urlparse, unquote

import requests
from bs4 import BeautifulSoup

# Try to import playwright for JS-rendered pages
try:
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    sync_playwright = None  # type: ignore
    PLAYWRIGHT_AVAILABLE = False

from PyQt5.QtCore import QThread, pyqtSignal
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGroupBox, QLineEdit, QPushButton, QCheckBox, QLabel,
    QTreeWidget, QTreeWidgetItem, QTextEdit, QProgressBar,
    QFileDialog, QMessageBox, QHeaderView
)

# Suppress warnings
warnings.filterwarnings('ignore')


class ScanWorker(QThread):
    """Worker thread for scanning URLs."""
    log_message = pyqtSignal(str)
    scan_complete = pyqtSignal(list)
    scan_error = pyqtSignal(str)

    def __init__(self, session, url, filter_text, follow_links, render_js=False):
        super().__init__()
        self.session = session
        self.url = url
        self.filter_text = filter_text
        self.follow_links = follow_links
        self.render_js = render_js

    def _fetch_with_playwright(self, url):
        """Fetch page content using Playwright for JS rendering."""
        if not PLAYWRIGHT_AVAILABLE or sync_playwright is None:
            raise RuntimeError("Playwright is not installed")
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_extra_http_headers({
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            })
            # Use 'load' instead of 'networkidle' - many sites never reach network idle due to ads/analytics
            page.goto(url, wait_until='load', timeout=60000)
            # Wait for content to render
            page.wait_for_timeout(2000)
            # Scroll down to trigger lazy loading
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            page.wait_for_timeout(2000)  # Wait for lazy-loaded content
            # Scroll back up and down to trigger more content
            page.evaluate('window.scrollTo(0, 0)')
            page.wait_for_timeout(500)
            page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
            page.wait_for_timeout(1500)
            content = page.content()
            browser.close()
            return content

    def run(self):
        try:
            found_pdfs = set()

            # Fetch the main page
            if self.render_js and PLAYWRIGHT_AVAILABLE:
                self.log_message.emit("Using browser to render JavaScript...")
                html_content = self._fetch_with_playwright(self.url)
                soup = BeautifulSoup(html_content, 'lxml')
            else:
                response = self.session.get(self.url, timeout=30)
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'lxml')

            # Find all links
            all_links = soup.find_all('a', href=True)
            self.log_message.emit(f"Found {len(all_links)} links on page")

            # Keywords that suggest script-related content
            script_keywords = [
                'script', 'screenplay', 'teleplay', 'pilot', 'episode',
                'transcript', 'draft', 'shooting', 'final'
            ]

            # URL patterns that indicate script detail pages (like /script/movie-name)
            script_page_patterns = [
                r'/script/[\w-]+',
                r'/scripts/[\w-]+',
                r'/screenplay/[\w-]+',
                r'/screenplays/[\w-]+',
            ]

            for link in all_links:
                href = str(link.get('href', ''))
                if not href:
                    continue
                full_url = urljoin(self.url, href)
                link_text = link.get_text().lower()

                # Check if it's a PDF link
                if self._is_pdf_link(full_url, href):
                    if self._matches_filter(full_url, link_text):
                        filename = self._extract_filename(full_url)
                        found_pdfs.add((filename, full_url))

                # Follow links if enabled
                elif self.follow_links:
                    combined = (link_text + ' ' + href.lower())
                    # Check if link matches script keywords or script page URL patterns
                    is_script_link = any(kw in combined for kw in script_keywords)
                    is_script_page = any(re.search(pattern, href) for pattern in script_page_patterns)
                    
                    if is_script_link or is_script_page:
                        try:
                            self.log_message.emit(f"Following link: {link_text[:50] if link_text else href[:50]}...")
                            sub_response = self.session.get(full_url, timeout=15)
                            sub_soup = BeautifulSoup(sub_response.text, 'lxml')

                            for sub_link in sub_soup.find_all('a', href=True):
                                sub_href = str(sub_link.get('href', ''))
                                if not sub_href:
                                    continue
                                sub_full_url = urljoin(full_url, sub_href)
                                sub_text = sub_link.get_text().lower()

                                if self._is_pdf_link(sub_full_url, sub_href):
                                    if self._matches_filter(sub_full_url, sub_text):
                                        filename = self._extract_filename(sub_full_url)
                                        found_pdfs.add((filename, sub_full_url))
                        except Exception as e:
                            self.log_message.emit(f"Could not follow link: {str(e)[:50]}")

            self.scan_complete.emit(list(found_pdfs))

        except Exception as e:
            self.scan_error.emit(str(e))

    def _is_pdf_link(self, url, href):
        """Check if a URL points to a PDF file."""
        url_lower = url.lower()
        href_lower = href.lower()
        parsed = urlparse(url_lower)
        path = parsed.path

        # Direct .pdf extension (handles query strings like file.pdf?v=123)
        if path.endswith('.pdf'):
            return True
        if href_lower.endswith('.pdf') or '.pdf?' in href_lower or '.pdf#' in href_lower:
            return True
        
        # Check for pdf in path segments
        if '/pdf/' in path or '/pdfs/' in path:
            return True
        
        # Known script hosting CDNs and domains
        script_pdf_domains = [
            'assets.scriptslug.com',
            'scriptslug.com/live/pdf',
            'dailyscript.com',
            'imsdb.com',
            'screenplaydb.com',
            'scriptpdf.com',
        ]
        if any(domain in url_lower for domain in script_pdf_domains):
            if 'pdf' in url_lower or path.endswith('.pdf'):
                return True
        
        # Download links with pdf indication
        if 'download' in url_lower and 'pdf' in url_lower:
            return True
        
        return False

    def _matches_filter(self, url, link_text):
        """Check if the PDF matches the user's filter."""
        if not self.filter_text:
            return True
        combined = (url.lower() + ' ' + link_text)
        return self.filter_text in combined

    def _extract_filename(self, url):
        """Extract a clean filename from a URL."""
        parsed = urlparse(url)
        path = unquote(parsed.path)
        filename = os.path.basename(path)
        
        # Remove query string from filename if present
        if '?' in filename:
            filename = filename.split('?')[0]

        if not filename or not filename.endswith('.pdf'):
            # Try to extract meaningful name from path
            path_parts = [p for p in path.split('/') if p]
            if path_parts:
                base_name = path_parts[-1]
                # Clean up the filename
                filename = re.sub(r'[^\w\-_.]', '_', base_name)
                if not filename.endswith('.pdf'):
                    filename += '.pdf'
            else:
                filename = 'script.pdf'
        
        return filename


class DownloadWorker(QThread):
    """Worker thread for downloading PDFs."""
    log_message = pyqtSignal(str)
    status_update = pyqtSignal(int, str)  # row index, status
    download_complete = pyqtSignal(int, int)  # success count, total count
    progress_update = pyqtSignal(bool)  # start/stop

    def __init__(self, session, items, download_dir):
        super().__init__()
        self.session = session
        self.items = items  # list of (row_index, filename, url)
        self.download_dir = download_dir

    def run(self):
        os.makedirs(self.download_dir, exist_ok=True)
        self.progress_update.emit(True)

        success_count = 0
        for row_index, filename, url in self.items:
            try:
                self.status_update.emit(row_index, "Downloading...")
                self.log_message.emit(f"Downloading: {filename}")

                response = self.session.get(url, timeout=60, stream=True)
                response.raise_for_status()

                filepath = os.path.join(self.download_dir, filename)
                if os.path.exists(filepath):
                    base, ext = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(filepath):
                        filepath = os.path.join(self.download_dir, f"{base}_{counter}{ext}")
                        counter += 1

                with open(filepath, 'wb') as f:
                    for chunk in response.iter_content(chunk_size=8192):
                        f.write(chunk)

                self.status_update.emit(row_index, "Downloaded")
                success_count += 1

            except Exception as e:
                self.log_message.emit(f"Failed to download {filename}: {str(e)}")
                self.status_update.emit(row_index, "Failed")

        self.progress_update.emit(False)
        self.download_complete.emit(success_count, len(self.items))


class ScriptFinder(QMainWindow):
    """Main application class for finding and downloading PDF scripts."""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Script Finder")
        self.setMinimumSize(600, 400)
        self.resize(800, 600)

        # Default download directory
        self.download_dir = os.path.expanduser("~/Downloads/Scripts")

        # Track state
        self.found_pdfs = []
        self.is_scanning = False
        self.scan_worker = None
        self.download_worker = None

        # Session for requests
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

        self._create_ui()

    def _create_ui(self):
        """Create the user interface."""
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setContentsMargins(10, 10, 10, 10)

        # URL Entry Section
        url_group = QGroupBox("Website URL")
        url_layout = QHBoxLayout(url_group)

        self.url_entry = QLineEdit()
        self.url_entry.setPlaceholderText("Enter URL to scan for scripts...")
        self.url_entry.setText("https://")
        self.url_entry.returnPressed.connect(self._start_scan)
        url_layout.addWidget(self.url_entry)

        self.scan_btn = QPushButton("Scan for Scripts")
        self.scan_btn.clicked.connect(self._start_scan)
        url_layout.addWidget(self.scan_btn)

        main_layout.addWidget(url_group)

        # Download Directory Section
        dir_group = QGroupBox("Download Directory")
        dir_layout = QHBoxLayout(dir_group)

        self.dir_entry = QLineEdit()
        self.dir_entry.setText(self.download_dir)
        dir_layout.addWidget(self.dir_entry)

        browse_btn = QPushButton("Browse...")
        browse_btn.clicked.connect(self._browse_directory)
        dir_layout.addWidget(browse_btn)

        main_layout.addWidget(dir_group)

        # Options Section
        options_group = QGroupBox("Options")
        options_layout = QVBoxLayout(options_group)

        checkbox_layout = QHBoxLayout()
        self.follow_links_check = QCheckBox("Follow links on page (find PDFs in linked pages)")
        self.follow_links_check.setChecked(True)
        checkbox_layout.addWidget(self.follow_links_check)

        self.auto_download_check = QCheckBox("Auto-download all found scripts")
        checkbox_layout.addWidget(self.auto_download_check)
        checkbox_layout.addStretch()
        options_layout.addLayout(checkbox_layout)

        # Second row of checkboxes
        checkbox_layout2 = QHBoxLayout()
        self.render_js_check = QCheckBox("Render JavaScript (for dynamic sites like ScriptSlug)")
        if not PLAYWRIGHT_AVAILABLE:
            self.render_js_check.setEnabled(False)
            self.render_js_check.setToolTip("Install playwright: pip install playwright && playwright install chromium")
        else:
            self.render_js_check.setToolTip("Uses a headless browser to render JavaScript-heavy pages")
        checkbox_layout2.addWidget(self.render_js_check)
        checkbox_layout2.addStretch()
        options_layout.addLayout(checkbox_layout2)

        filter_layout = QHBoxLayout()
        filter_layout.addWidget(QLabel("Filter (optional):"))
        self.filter_entry = QLineEdit()
        self.filter_entry.setMaximumWidth(300)
        filter_layout.addWidget(self.filter_entry)
        filter_layout.addWidget(QLabel("(e.g., 'screenplay', 'pilot')"))
        filter_layout.addStretch()
        options_layout.addLayout(filter_layout)

        main_layout.addWidget(options_group)

        # Results Section
        results_group = QGroupBox("Found Scripts")
        results_layout = QVBoxLayout(results_group)

        self.results_tree = QTreeWidget()
        self.results_tree.setHeaderLabels(["Filename", "URL", "Status"])
        self.results_tree.setSelectionMode(QTreeWidget.ExtendedSelection)
        self.results_tree.setAlternatingRowColors(True)
        header = self.results_tree.header()
        if header:
            header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
            header.setSectionResizeMode(1, QHeaderView.Stretch)
            header.setSectionResizeMode(2, QHeaderView.ResizeToContents)
        results_layout.addWidget(self.results_tree)

        btn_layout = QHBoxLayout()
        self.download_selected_btn = QPushButton("Download Selected")
        self.download_selected_btn.clicked.connect(self._download_selected)
        self.download_selected_btn.setEnabled(False)
        btn_layout.addWidget(self.download_selected_btn)

        self.download_all_btn = QPushButton("Download All")
        self.download_all_btn.clicked.connect(self._download_all)
        self.download_all_btn.setEnabled(False)
        btn_layout.addWidget(self.download_all_btn)

        clear_btn = QPushButton("Clear Results")
        clear_btn.clicked.connect(self._clear_results)
        btn_layout.addWidget(clear_btn)

        btn_layout.addStretch()
        results_layout.addLayout(btn_layout)

        main_layout.addWidget(results_group, stretch=1)

        # Log Section
        log_group = QGroupBox("Log")
        log_layout = QVBoxLayout(log_group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(120)
        log_layout.addWidget(self.log_text)

        main_layout.addWidget(log_group)

        # Progress Bar
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)  # Indeterminate
        self.progress.setVisible(False)
        main_layout.addWidget(self.progress)

    def _log(self, message):
        """Add a message to the log."""
        self.log_text.append(message)

    def _browse_directory(self):
        """Open directory browser dialog."""
        directory = QFileDialog.getExistingDirectory(
            self, "Select Download Directory", self.download_dir
        )
        if directory:
            self.download_dir = directory
            self.dir_entry.setText(directory)

    def _clear_results(self):
        """Clear the results tree."""
        self.results_tree.clear()
        self.found_pdfs = []
        self.download_selected_btn.setEnabled(False)
        self.download_all_btn.setEnabled(False)

    def _start_scan(self):
        """Start scanning the URL for PDF scripts."""
        if self.is_scanning:
            return

        url = self.url_entry.text().strip()
        if not url or url == "https://":
            QMessageBox.warning(self, "Warning", "Please enter a valid URL")
            return

        if not url.startswith(("http://", "https://")):
            url = "https://" + url
            self.url_entry.setText(url)

        self._clear_results()
        self.is_scanning = True
        self.scan_btn.setEnabled(False)
        self.progress.setVisible(True)
        self._log(f"Scanning: {url}")

        # Create and start worker thread
        filter_text = self.filter_entry.text().strip().lower()
        follow_links = self.follow_links_check.isChecked()
        render_js = self.render_js_check.isChecked() and PLAYWRIGHT_AVAILABLE

        self.scan_worker = ScanWorker(self.session, url, filter_text, follow_links, render_js)
        self.scan_worker.log_message.connect(self._log)
        self.scan_worker.scan_complete.connect(self._scan_complete)
        self.scan_worker.scan_error.connect(self._scan_error)
        self.scan_worker.start()

    def _scan_complete(self, pdfs):
        """Handle scan completion."""
        self.is_scanning = False
        self.scan_btn.setEnabled(True)
        self.progress.setVisible(False)

        self.found_pdfs = pdfs

        if pdfs:
            for filename, url in pdfs:
                item = QTreeWidgetItem([filename, url, "Ready"])
                self.results_tree.addTopLevelItem(item)

            self.download_selected_btn.setEnabled(True)
            self.download_all_btn.setEnabled(True)
            self._log(f"Found {len(pdfs)} PDF script(s)")

            if self.auto_download_check.isChecked():
                self._download_all()
        else:
            self._log("No PDF scripts found on this page")

    def _scan_error(self, error):
        """Handle scan error."""
        self.is_scanning = False
        self.scan_btn.setEnabled(True)
        self.progress.setVisible(False)
        self._log(f"Error: {error}")
        QMessageBox.critical(self, "Error", f"Failed to scan URL:\n{error}")

    def _download_selected(self):
        """Download selected PDFs."""
        selected = self.results_tree.selectedItems()
        if not selected:
            QMessageBox.warning(self, "Warning", "Please select scripts to download")
            return

        items = []
        for item in selected:
            row_index = self.results_tree.indexOfTopLevelItem(item)
            filename = item.text(0)
            url = item.text(1)
            items.append((row_index, filename, url))

        self._start_download(items)

    def _download_all(self):
        """Download all found PDFs."""
        items = []
        for i in range(self.results_tree.topLevelItemCount()):
            item = self.results_tree.topLevelItem(i)
            if item:
                items.append((i, item.text(0), item.text(1)))

        if items:
            self._start_download(items)

    def _start_download(self, items):
        """Start the download worker thread."""
        download_dir = self.dir_entry.text()

        self.download_worker = DownloadWorker(self.session, items, download_dir)
        self.download_worker.log_message.connect(self._log)
        self.download_worker.status_update.connect(self._update_status)
        self.download_worker.download_complete.connect(self._download_complete)
        self.download_worker.progress_update.connect(self._set_progress_visible)
        self.download_worker.start()

    def _set_progress_visible(self, visible):
        """Show or hide the progress bar."""
        self.progress.setVisible(visible)

    def _update_status(self, row_index, status):
        """Update the status column for a tree item."""
        item = self.results_tree.topLevelItem(row_index)
        if item:
            item.setText(2, status)

    def _download_complete(self, success_count, total_count):
        """Handle download completion."""
        self._log(f"Download complete: {success_count}/{total_count} files")
        download_dir = self.dir_entry.text()

        if success_count > 0:
            QMessageBox.information(
                self, "Download Complete",
                f"Successfully downloaded {success_count} script(s) to:\n{download_dir}"
            )


def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    
    # Apply dark mode stylesheet
    dark_stylesheet = """
        QMainWindow, QWidget {
            background-color: #1e1e1e;
            color: #d4d4d4;
        }
        
        QGroupBox {
            border: 1px solid #3e3e3e;
            border-radius: 5px;
            margin-top: 10px;
            padding-top: 10px;
            font-weight: bold;
            color: #d4d4d4;
        }
        
        QGroupBox::title {
            subcontrol-origin: margin;
            left: 10px;
            padding: 0 5px;
        }
        
        QLineEdit {
            background-color: #2d2d2d;
            border: 1px solid #3e3e3e;
            border-radius: 3px;
            padding: 5px;
            color: #d4d4d4;
            selection-background-color: #264f78;
        }
        
        QLineEdit:focus {
            border: 1px solid #007acc;
        }
        
        QPushButton {
            background-color: #0e639c;
            border: 1px solid #0e639c;
            border-radius: 3px;
            padding: 6px 12px;
            color: #ffffff;
            font-weight: bold;
        }
        
        QPushButton:hover {
            background-color: #1177bb;
            border: 1px solid #1177bb;
        }
        
        QPushButton:pressed {
            background-color: #005a9e;
        }
        
        QPushButton:disabled {
            background-color: #3e3e3e;
            border: 1px solid #3e3e3e;
            color: #6e6e6e;
        }
        
        QCheckBox {
            color: #d4d4d4;
            spacing: 5px;
        }
        
        QCheckBox::indicator {
            width: 18px;
            height: 18px;
            border: 1px solid #3e3e3e;
            border-radius: 3px;
            background-color: #2d2d2d;
        }
        
        QCheckBox::indicator:checked {
            background-color: #0e639c;
            border: 1px solid #0e639c;
            image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTYiIGhlaWdodD0iMTYiIHZpZXdCb3g9IjAgMCAxNiAxNiIgeG1sbnM9Imh0dHA6Ly93d3cudzMub3JnLzIwMDAvc3ZnIj48cGF0aCBkPSJNNi41IDEybC00LjUtNC41TDMuNSA2bDMgM0wxMyAzbDEuNSAxLjV6IiBmaWxsPSIjZmZmIi8+PC9zdmc+);
        }
        
        QCheckBox::indicator:hover {
            border: 1px solid #007acc;
        }
        
        QTreeWidget {
            background-color: #252526;
            border: 1px solid #3e3e3e;
            border-radius: 3px;
            color: #d4d4d4;
            alternate-background-color: #2d2d30;
            selection-background-color: #264f78;
        }
        
        QTreeWidget::item {
            padding: 4px;
        }
        
        QTreeWidget::item:hover {
            background-color: #2a2d2e;
        }
        
        QTreeWidget::item:selected {
            background-color: #264f78;
        }
        
        QHeaderView::section {
            background-color: #2d2d2d;
            color: #d4d4d4;
            padding: 5px;
            border: none;
            border-right: 1px solid #3e3e3e;
            border-bottom: 1px solid #3e3e3e;
            font-weight: bold;
        }
        
        QTextEdit {
            background-color: #1e1e1e;
            border: 1px solid #3e3e3e;
            border-radius: 3px;
            color: #d4d4d4;
            selection-background-color: #264f78;
        }
        
        QProgressBar {
            border: 1px solid #3e3e3e;
            border-radius: 3px;
            background-color: #2d2d2d;
            text-align: center;
            color: #d4d4d4;
        }
        
        QProgressBar::chunk {
            background-color: #0e639c;
            border-radius: 2px;
        }
        
        QLabel {
            color: #d4d4d4;
        }
        
        QScrollBar:vertical {
            background-color: #1e1e1e;
            width: 12px;
            border: none;
        }
        
        QScrollBar::handle:vertical {
            background-color: #424242;
            border-radius: 6px;
            min-height: 20px;
        }
        
        QScrollBar::handle:vertical:hover {
            background-color: #4e4e4e;
        }
        
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
            height: 0px;
        }
        
        QScrollBar:horizontal {
            background-color: #1e1e1e;
            height: 12px;
            border: none;
        }
        
        QScrollBar::handle:horizontal {
            background-color: #424242;
            border-radius: 6px;
            min-width: 20px;
        }
        
        QScrollBar::handle:horizontal:hover {
            background-color: #4e4e4e;
        }
        
        QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
            width: 0px;
        }
        
        QMessageBox {
            background-color: #1e1e1e;
        }
        
        QMessageBox QLabel {
            color: #d4d4d4;
        }
    """
    
    app.setStyleSheet(dark_stylesheet)
    
    window = ScriptFinder()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
