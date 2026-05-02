from pathlib import Path

from flask import Flask, render_template, request, send_file, flash, redirect, url_for, send_from_directory
from jinja2 import ChoiceLoader, FileSystemLoader
import os
from werkzeug.utils import secure_filename
import tempfile
from datetime import datetime
import requests
from csv import reader, writer
import time
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

_REPO_ROOT = Path(__file__).resolve().parent.parent
_SHARED_UI = _REPO_ROOT / "shared" / "chesstools-ui"

app = Flask(__name__)
app.jinja_loader = ChoiceLoader(
    [
        FileSystemLoader(Path(__file__).resolve().parent / "templates"),
        FileSystemLoader(_SHARED_UI / "templates"),
    ]
)


@app.route("/chesstools-ui/<path:filename>")
def chesstools_ui_assets(filename):
    return send_from_directory(_SHARED_UI / "static", filename)


# Configuration from environment variables
app.secret_key = os.environ.get('SECRET_KEY', 'change-this-to-a-random-secret-key-for-production-213423jgasd')

# Application Configuration
UPLOAD_FOLDER = os.environ.get('UPLOAD_FOLDER', 'uploads')
ALLOWED_EXTENSIONS = set(os.environ.get('ALLOWED_EXTENSIONS', 'csv').split(','))
MAX_FILE_SIZE = int(os.environ.get('MAX_FILE_SIZE', 16 * 1024 * 1024))  # 16MB default

# CFC API Configuration
CFC_API_BASE_URL = os.environ.get('CFC_API_BASE_URL', 'https://server.chess.ca/api/player/v1')
API_TIMEOUT = int(os.environ.get('API_TIMEOUT', 10))
API_RATE_LIMIT_DELAY = float(os.environ.get('API_RATE_LIMIT_DELAY', 0.1))

# Event Configuration
DEFAULT_EVENT_DATE = os.environ.get('DEFAULT_EVENT_DATE', '2025-06-16')
DEFAULT_CFC_ID_COLUMN = int(os.environ.get('DEFAULT_CFC_ID_COLUMN', 2))

# File Processing Configuration
MAX_PLAYERS_PER_FILE = int(os.environ.get('MAX_PLAYERS_PER_FILE', 1000))
PROCESSING_TIMEOUT = int(os.environ.get('PROCESSING_TIMEOUT', 300))

# Create upload directory if it doesn't exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE


def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def get_profile(cfcid):
    """Get player profile from CFC API"""
    URL = f"{CFC_API_BASE_URL}/{cfcid}"
    try:
        page = requests.get(URL, timeout=API_TIMEOUT)
        return page.json()
    except requests.RequestException as e:
        print(f"Error fetching profile for {cfcid}: {e}")
        return None


def process_csv_file(file_path, event_date, cfc_id_index=2, options=None):
    """Process the uploaded CSV file and add ratings based on user options"""
    if options is None:
        options = {
            'include_regular': True,
            'include_quick': True,
            'include_membership': True,
            'include_expiry_date': False,
            'include_fide_id': True,
            'include_names': True,
            'sort_by': 'regular'  # regular, quick, name, none
        }
    
    id_list = []
    new_csv_rows = []
    
    with open(file_path, 'r') as f:
        csv_reader = reader(f)
        header = next(csv_reader)  # skip the header

        for row in csv_reader:
            print(f"Processing row: {row}")
            cfc_id = row[cfc_id_index] if len(row) > cfc_id_index else ''

            data_to_write = row[0:cfc_id_index + 1]  # keep the first few indices
            
            if cfc_id != '':  # if the id is not empty
                if cfc_id.lower() == "na" or cfc_id.lower() == "n/a":
                    # Add empty values based on selected options
                    if options['include_regular']:
                        data_to_write.append("0")
                    if options['include_quick']:
                        data_to_write.append("0")
                    if options['include_membership']:
                        data_to_write.append("")
                        if options['include_expiry_date']:
                            data_to_write.append("")
                    if options['include_fide_id']:
                        data_to_write.append("")
                    if options['include_names']:
                        data_to_write.extend(["", ""])
                    
                    # Add remaining columns from original row
                    if len(row) > cfc_id_index + 1:
                        data_to_write += row[cfc_id_index + 1:]
                    
                    new_csv_rows.append(data_to_write)
                    continue

                if cfc_id in id_list: 
                    continue
                id_list.append(cfc_id)

                profile = get_profile(cfc_id)
                
                if profile is None:
                    # Profile not found - add empty values for all options
                    if options['include_regular']:
                        data_to_write.append("0")
                    if options['include_quick']:
                        data_to_write.append("0")
                    if options['include_membership']:
                        data_to_write.append("")
                        if options['include_expiry_date']:
                            data_to_write.append("")
                    if options['include_fide_id']:
                        data_to_write.append("")
                    if options['include_names']:
                        data_to_write.extend(["", ""])
                        
                    # Add remaining columns from original row
                    if len(row) > cfc_id_index + 1:
                        data_to_write += row[cfc_id_index + 1:]
                    
                    new_csv_rows.append(data_to_write)
                    continue
                elif profile.get("player", {}).get("events") == []:
                    # Profile found but no events - still get available info like names
                    if options['include_regular']:
                        data_to_write.append("0")
                    if options['include_quick']:
                        data_to_write.append("0")
                    if options['include_membership']:
                        # Check membership even if no events
                        cfc_expiry = profile["player"].get("cfc_expiry", "")
                        if not cfc_expiry.strip():
                            data_to_write.append("NA")
                            if options['include_expiry_date']:
                                data_to_write.append("")
                        else:
                            try:
                                expiry_date = datetime.strptime(cfc_expiry, '%Y-%m-%d')
                                if expiry_date < event_date:
                                    data_to_write.append("Expired")
                                else:
                                    data_to_write.append("Valid")
                                
                                # Add actual expiry date if requested
                                if options['include_expiry_date']:
                                    data_to_write.append(cfc_expiry)
                            except ValueError:
                                data_to_write.append("NA")
                                if options['include_expiry_date']:
                                    data_to_write.append("")
                    if options['include_fide_id']:
                        data_to_write.append(profile["player"].get("fide_id", ""))
                    if options['include_names']:
                        data_to_write.append(profile["player"].get("name_first", ""))
                        data_to_write.append(profile["player"].get("name_last", ""))
                        
                    # Add remaining columns from original row
                    if len(row) > cfc_id_index + 1:
                        data_to_write += row[cfc_id_index + 1:]
                    
                    new_csv_rows.append(data_to_write)
                    continue
                else:
                    # Add ratings based on user selection
                    if options['include_regular']:
                        regular_rating = profile["player"].get("regular_rating", 0)
                        data_to_write.append(regular_rating)
                    if options['include_quick']:
                        quick_rating = profile["player"].get("quick_rating", 0)
                        data_to_write.append(quick_rating)

                # Check CFC membership expiry (if requested)
                if options['include_membership']:
                    cfc_expiry = profile["player"].get("cfc_expiry", "")
                    if not cfc_expiry.strip():
                        data_to_write.append("NA")
                        if options['include_expiry_date']:
                            data_to_write.append("")
                    else:
                        try:
                            expiry_date = datetime.strptime(cfc_expiry, '%Y-%m-%d')
                            if expiry_date < event_date:
                                data_to_write.append("Expired")
                            else:
                                data_to_write.append("Valid")
                            
                            # Add actual expiry date if requested
                            if options['include_expiry_date']:
                                data_to_write.append(cfc_expiry)
                        except ValueError:
                            data_to_write.append("NA")
                            if options['include_expiry_date']:
                                data_to_write.append("")

                # Add additional player information based on options
                if options['include_fide_id']:
                    data_to_write.append(profile["player"].get("fide_id", ""))
                if options['include_names']:
                    data_to_write.append(profile["player"].get("name_first", ""))
                    data_to_write.append(profile["player"].get("name_last", ""))
                
                # Add remaining columns from original row
                if len(row) > cfc_id_index + 1:
                    data_to_write += row[cfc_id_index + 1:]

                new_csv_rows.append(data_to_write)
                
                # Add a small delay to be respectful to the API
                time.sleep(API_RATE_LIMIT_DELAY)

    # Create new header based on selected options
    new_header = header[0:cfc_id_index + 1]
    column_index = cfc_id_index + 1
    
    if options['include_regular']:
        new_header.append("CFC Regular Rating")
        regular_rating_index = column_index
        column_index += 1
    else:
        regular_rating_index = None
        
    if options['include_quick']:
        new_header.append("CFC Quick Rating")
        quick_rating_index = column_index
        column_index += 1
    else:
        quick_rating_index = None
        
    if options['include_membership']:
        new_header.append("CFC Membership")
        column_index += 1
        if options['include_expiry_date']:
            new_header.append("Expiry Date")
            column_index += 1
        
    if options['include_fide_id']:
        new_header.append("FIDE ID")
        column_index += 1
        
    if options['include_names']:
        new_header.extend(["First Name", "Last Name"])
        name_index = column_index
        column_index += 2
    else:
        name_index = None
    
    # Add remaining original columns
    if len(header) > cfc_id_index + 1:
        new_header += header[cfc_id_index + 1:]
    
    # Sort data based on user preference
    sorted_data = sort_by_preference(new_csv_rows, options, regular_rating_index, quick_rating_index, name_index)
    
    return new_header, sorted_data


def sort_by_preference(data, options, regular_rating_index=None, quick_rating_index=None, name_index=None):
    """Sort data based on user preference and update rankings"""
    
    def get_sort_key(row):
        if options['sort_by'] == 'regular' and regular_rating_index is not None:
            try:
                return int(row[regular_rating_index]) if row[regular_rating_index] and row[regular_rating_index] != "" else 0
            except (ValueError, IndexError):
                return 0
        elif options['sort_by'] == 'quick' and quick_rating_index is not None:
            try:
                return int(row[quick_rating_index]) if row[quick_rating_index] and row[quick_rating_index] != "" else 0
            except (ValueError, IndexError):
                return 0
        elif options['sort_by'] == 'name' and name_index is not None:
            try:
                # Sort by last name, then first name
                last_name = row[name_index + 1] if len(row) > name_index + 1 else ""
                first_name = row[name_index] if len(row) > name_index else ""
                return (last_name.lower(), first_name.lower())
            except IndexError:
                return ("", "")
        elif options['sort_by'] == 'combined' and regular_rating_index is not None and quick_rating_index is not None:
            try:
                regular = int(row[regular_rating_index]) if row[regular_rating_index] and row[regular_rating_index] != "" else 0
                quick = int(row[quick_rating_index]) if row[quick_rating_index] and row[quick_rating_index] != "" else 0
                return (regular, quick)
            except (ValueError, IndexError):
                return (0, 0)
        else:
            # No sorting - maintain original order
            return 0
    
    # Only sort if not 'none'
    if options['sort_by'] != 'none':
        reverse_sort = options['sort_by'] in ['regular', 'quick', 'combined']  # Ratings sort descending, names ascending
        data.sort(key=get_sort_key, reverse=reverse_sort)

    # Update rankings
    rankings_number = 1
    for line in data:
        line[0] = rankings_number  # assume that the first value is the rankings
        rankings_number += 1

    return data


def sort_by_rating(data, regular_rating_index, quick_rating_index):
    """Legacy function - kept for backwards compatibility"""
    options = {'sort_by': 'combined'}
    return sort_by_preference(data, options, regular_rating_index, quick_rating_index)


def write_to_file(filename, header, contents):
    """Write processed data to CSV file"""
    with open(filename, 'w', encoding='UTF8', newline='') as f:
        write = writer(f)
        write.writerow(header)
        for content in contents:
            write.writerow(content)


@app.route('/')
def index():
    """Main page with file upload form"""
    return render_template('index.html')

@app.route('/download/<filename>')
def download_file(filename):
    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
    return send_file(
        file_path,
        as_attachment=True,
        download_name=filename,
        mimetype='text/csv'
    )
    

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        flash('No file selected')
        return redirect(request.url)
    
    file = request.files['file']
    if file.filename == '':
        flash('No file selected')
        return redirect(request.url)
    
    if file and allowed_file(file.filename):
        event_date_str = request.form.get('event_date')
        cfc_id_column = int(request.form.get('cfc_id_column', DEFAULT_CFC_ID_COLUMN))
        
        # Get user options from form
        options = {
            'include_regular': request.form.get('include_regular') == 'on',
            'include_quick': request.form.get('include_quick') == 'on',
            'include_membership': request.form.get('include_membership') == 'on',
            'include_expiry_date': request.form.get('include_expiry_date') == 'on',
            'include_fide_id': request.form.get('include_fide_id') == 'on',
            'include_names': request.form.get('include_names') == 'on',
            'sort_by': request.form.get('sort_by', 'regular')
        }
        
        try:
            event_date = datetime.strptime(event_date_str, '%Y-%m-%d') if event_date_str else datetime.now()
            filename = secure_filename(file.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{timestamp}_{filename}"
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(file_path)

            flash('Processing your file... This may take a few minutes.')
            header, processed_data = process_csv_file(file_path, event_date, cfc_id_column, options)

            if len(processed_data) > MAX_PLAYERS_PER_FILE:
                flash(f'File too large! Maximum {MAX_PLAYERS_PER_FILE} players allowed. Your file has {len(processed_data)} players.')
                os.remove(file_path)
                return redirect(url_for('index'))

            output_filename = f"processed_{filename}"
            output_path = os.path.join(app.config['UPLOAD_FOLDER'], output_filename)
            write_to_file(output_path, header, processed_data)

            os.remove(file_path)

            flash(f'File processed successfully! {len(processed_data)} players processed.')
            return render_template(
                'index.html',
                headers=header,
                rows=processed_data,
                download_url=url_for('download_file', filename=output_filename),
                options=options  # Pass options back to template for display
            )

        except Exception as e:
            flash(f'Error processing file: {str(e)}')
            return redirect(url_for('index'))
    else:
        flash('Invalid file type. Please upload a CSV file.')
        return redirect(url_for('index'))


@app.route('/about')
def about():
    """About page explaining how to use the tool"""
    return render_template('about.html')


@app.route('/sample')
def download_sample():
    """Download sample CSV file"""
    sample_path = os.path.join(os.getcwd(), 'samples/sample_tournament.csv')
    return send_file(
        sample_path,
        as_attachment=True,
        download_name='sample_tournament.csv',
        mimetype='text/csv'
    )


@app.route('/sample-small')
def download_sample_small():
    """Download small sample CSV file for quick testing"""
    sample_path = os.path.join(os.getcwd(), 'samples/sample_small.csv')
    return send_file(
        sample_path,
        as_attachment=True,
        download_name='sample_small.csv',
        mimetype='text/csv'
    )


if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5001)
