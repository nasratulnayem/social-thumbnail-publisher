import os
import csv
import asyncio
import uuid
import json
import zipfile
import io
import re
import random
from flask import (
    Flask,
    render_template,
    request,
    redirect,
    url_for,
    send_from_directory,
    flash,
    render_template_string,
    jsonify,
)
from playwright.async_api import async_playwright
from werkzeug.utils import secure_filename

# --- App Initialization ---
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY')
if not app.secret_key:
    raise RuntimeError('FLASK_SECRET_KEY environment variable is required')

# --- Configuration ---
UPLOAD_FOLDER = 'uploads'
GENERATED_FOLDER = 'generated'
TEMPLATE_FOLDER = 'thumbnail_templates'
IMAGE_UPLOAD_FOLDER = 'image_uploads' # New folder for uploaded images
DB_FILE = 'db.json'
ALLOWED_EXTENSIONS = {'csv', 'html', 'png', 'jpg', 'jpeg', 'gif'}
VIDEO_EXTENSIONS = [".mp4", ".mov", ".avi", ".webm", ".mkv"]

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['GENERATED_FOLDER'] = GENERATED_FOLDER
app.config['TEMPLATE_FOLDER'] = TEMPLATE_FOLDER
app.config['IMAGE_UPLOAD_FOLDER'] = IMAGE_UPLOAD_FOLDER # Add to app config

# --- Helper Functions ---

def init_db():
    """Initializes the JSON database if it doesn't exist."""
    if not os.path.exists(DB_FILE):
        with open(DB_FILE, 'w') as f:
            json.dump({"thumbnails": [], "social_media_credentials": {}}, f)

def get_page_access_token(user_token, page_id):
    """Exchange user token for page token."""
    url = f"https://graph.facebook.com/v19.0/{page_id}"
    params = {"fields": "access_token", "access_token": user_token}
    try:
        r = requests.get(url, params=params)
        r.raise_for_status()  # Raise an exception for bad status codes
        data = r.json()
        if "access_token" in data:
            return data["access_token"], None
        else:
            error_message = data.get("error", {}).get("message", "Failed to get page access token.")
            return None, error_message
    except requests.exceptions.RequestException as e:
        return None, str(e)

def get_db():
    """Reads the entire database, ensuring default keys exist."""
    with open(DB_FILE, 'r') as f:
        data = json.load(f)
    if 'social_media_credentials' not in data:
        data['social_media_credentials'] = {}
    return data

def write_db(data):
    """Writes data to the database."""
    with open(DB_FILE, 'w') as f:
        json.dump(data, f, indent=4)

def allowed_file(filename):
    """Checks if the file extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def generate_slug(text):
    """Generates a URL-friendly slug from a string."""
    if not text:
        return "no-title"
    slug = text.lower()
    slug = re.sub(r'[^a-z0-9\s-]', '', slug) # remove special characters
    slug = re.sub(r'[\s-]+', '-', slug).strip('-') # replace spaces and hyphens with a single hyphen
    return slug

async def create_thumbnail(html_content, output_filename):
    """Renders HTML content using Playwright and saves a screenshot."""
    output_path = os.path.join(app.config['GENERATED_FOLDER'], output_filename)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1280, "height": 720})
        
        # Get the base URL for resolving local paths and inject it into the HTML.
        base_url = url_for('index', _external=True)
        if '<head>' in html_content:
            html_with_base = html_content.replace('<head>', f'<head>\n    <base href="{base_url}">')
        else:
            html_with_base = f'<base href="{base_url}">{html_content}'

        await page.set_content(html_with_base, timeout=60000)
        await page.screenshot(path=output_path, type="png")
        await browser.close()

# --- Routes ---

@app.route('/')
def index():
    """Main page: displays templates and generated thumbnails."""
    db = get_db()
    thumbnails = sorted(db['thumbnails'], key=lambda x: x.get('created_at', 0), reverse=True)
    
    template_files = os.listdir(app.config['TEMPLATE_FOLDER'])
    templates = [f for f in template_files if f.endswith('.html')]
    
    return render_template('index.html', thumbnails=thumbnails, templates=templates)

@app.route('/post_to_facebook/<thumbnail_id>')
def post_to_facebook(thumbnail_id):
    """Displays the Facebook posting interface for a specific thumbnail."""
    db = get_db()
    thumbnail = next((item for item in db['thumbnails'] if item['id'] == thumbnail_id), None)
    if not thumbnail:
        flash('Thumbnail not found.')
        return redirect(url_for('index'))
    
    return render_template('facebook_post.html', thumbnail=thumbnail)

@app.route('/social_hub/<thumbnail_id>')
def social_hub(thumbnail_id):
    """Displays the new Social Post Hub for a specific thumbnail."""
    db = get_db()
    thumbnail = next((item for item in db['thumbnails'] if item['id'] == thumbnail_id), None)
    if not thumbnail:
        flash('Thumbnail not found.')
        return redirect(url_for('index'))
    return render_template('social_hub.html', thumbnail=thumbnail)

@app.route('/settings')
def settings():
    """Displays the settings page for social media credentials."""
    db = get_db()
    credentials = db.get('social_media_credentials', {})
    image_urls = db.get('image_urls', [])
    return render_template('settings.html', credentials=credentials, image_urls=image_urls)

@app.route('/save_image_urls', methods=['POST'])
def save_image_urls():
    """Saves the list of image URLs to the database."""
    db = get_db()
    urls = request.form.get('image_urls', '').splitlines()
    # Filter out any empty lines
    db['image_urls'] = [url.strip() for url in urls if url.strip()]
    write_db(db)
    flash('Image URLs saved successfully!', 'success')
    return redirect(url_for('settings'))

@app.route('/save_settings', methods=['POST'])
def save_settings():
    """Saves social media credentials to the database."""
    db = get_db()
    db['social_media_credentials']['facebook_access_token'] = request.form.get('facebook_access_token')
    db['social_media_credentials']['facebook_page_id'] = request.form.get('facebook_page_id')
    write_db(db)
    flash('Facebook credentials saved successfully!', 'success')
    return redirect(url_for('settings'))

import requests
from datetime import datetime, timedelta
import time
import pytz # For timezone handling

# ... (other imports)

@app.route('/publish_facebook_post/<thumbnail_id>', methods=['POST'])
def publish_facebook_post(thumbnail_id):
    """Handles publishing or scheduling a Facebook post, with optional custom media."""
    db = get_db()
    credentials = db.get('social_media_credentials', {})
    user_access_token = credentials.get('facebook_access_token')
    page_id = credentials.get('facebook_page_id')

    if not user_access_token or not page_id:
        return jsonify({'status': 'error', 'message': 'Facebook credentials not set. Please go to Settings.'})

    page_access_token, error = get_page_access_token(user_access_token, page_id)
    if error:
        return jsonify({'status': 'error', 'message': f'Facebook Auth Error: {error}'})

    thumbnail = next((item for item in db['thumbnails'] if item['id'] == thumbnail_id), None)
    if not thumbnail:
        return jsonify({'status': 'error', 'message': 'Thumbnail not found.'})

    caption = request.form.get('caption', '')
    first_comment = request.form.get('first_comment', '')
    schedule_option = request.form.get('schedule_option', 'now')
    schedule_datetime_str = request.form.get('schedule_datetime')

    media_path = None
    try:
        # Check for custom uploaded media
        if 'custom_media' in request.files and request.files['custom_media'].filename != '':
            custom_file = request.files['custom_media']
            filename = secure_filename(f"custom_{uuid.uuid4()}_{custom_file.filename}")
            media_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            custom_file.save(media_path)
        else:
            # Fallback to the generated thumbnail
            media_path = os.path.join(app.config['GENERATED_FOLDER'], thumbnail['filename'])

        if not os.path.exists(media_path):
            return jsonify({'status': 'error', 'message': 'Media file not found on server.'})

        # Determine if the file is a video
        _, ext = os.path.splitext(media_path.lower())
        is_video = ext in VIDEO_EXTENSIONS

        # Step 1: Upload the media to get an ID.
        endpoint = 'videos' if is_video else 'photos'
        upload_url = f"https://graph.facebook.com/{page_id}/{endpoint}"
        
        payload = {
            'access_token': page_access_token,
            'published': False
        }
        
        with open(media_path, 'rb') as f:
            files = {'source': f}
            if is_video:
                upload_response = requests.post(upload_url, data=payload, files=files, timeout=600) # 10 minute timeout for videos
            else:
                upload_response = requests.post(upload_url, data=payload, files=files)
        
        upload_response_data = upload_response.json()

        if upload_response.status_code != 200 or 'id' not in upload_response_data:
            error_message = upload_response_data.get('error', {}).get('message', 'Failed to upload media to Facebook.')
            return jsonify({'status': 'error', 'message': error_message})

        media_id = upload_response_data['id']

        # Step 2: Create the post on the page's feed using the media ID.
        post_url = f"https://graph.facebook.com/{page_id}/feed"
        post_params = {
            'access_token': page_access_token,
            'message': caption,
            'attached_media[0]': f"{{'media_fbid': '{media_id}'}}"
        }

        if schedule_option == 'schedule':
            if not schedule_datetime_str:
                return jsonify({'status': 'error', 'message': 'A schedule time is required.'})

            dhaka_tz = pytz.timezone('Asia/Dhaka')
            schedule_dt_naive = datetime.strptime(schedule_datetime_str, "%Y-%m-%d %H:%M")
            schedule_dt_dhaka = dhaka_tz.localize(schedule_dt_naive)
            scheduled_publish_time = int(schedule_dt_dhaka.timestamp())

            if scheduled_publish_time < int(time.time()) + 600:
                return jsonify({'status': 'error', 'message': 'Scheduled time must be at least 10 minutes in the future.'})
            
            post_params['scheduled_publish_time'] = scheduled_publish_time
            post_params['published'] = False

        response = requests.post(post_url, params=post_params)
        response_data = response.json()

        if response.status_code == 200 and 'id' in response_data:
            post_id = response_data['id']
            if first_comment:
                comment_url = f"https://graph.facebook.com/{post_id}/comments"
                comment_params = {'access_token': page_access_token, 'message': first_comment}
                requests.post(comment_url, params=comment_params)

            message = f"Post {'scheduled' if schedule_option == 'schedule' else 'published'} successfully! Post ID: {post_id}"
            return jsonify({'status': 'success', 'message': message})
        else:
            error_message = response_data.get('error', {}).get('message', 'Unknown Facebook API error.')
            return jsonify({'status': 'error', 'message': f'Failed to publish/schedule post: {error_message}'})

    except Exception as e:
        return jsonify({'status': 'error', 'message': f'An unexpected error occurred: {e}'})
    finally:
        # Clean up temporary custom upload
        if 'custom_media' in request.files and media_path and os.path.exists(media_path):
            if "custom_" in media_path: # Basic safety check
                os.remove(media_path)

# --- Main Execution ---

@app.route('/uploads/image/<filename>')
def uploaded_image(filename):
    """Serves an image from the image_uploads directory."""
    return send_from_directory(app.config['IMAGE_UPLOAD_FOLDER'], filename)

@app.route('/upload_csv', methods=['POST'])
def upload_csv():
    """Handles CSV upload, data processing, and thumbnail generation."""
    if 'file' not in request.files:
        flash('No file part')
        return redirect(url_for('index'))
    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('index'))

    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(filepath)
        
        template_name = request.form.get('template')
        if not template_name:
            flash('No template selected')
            return redirect(url_for('index'))

        template_path = os.path.join(app.config['TEMPLATE_FOLDER'], template_name)
        with open(template_path, 'r') as f:
            html_template_str = f.read()

        db = get_db()
        try:
            with open(filepath, 'r', encoding='utf-8') as csvfile:
                reader = csv.DictReader(csvfile)
                for row in reader:
                    # Generate a unique ID for the thumbnail record
                    unique_id = str(uuid.uuid4())
                    
                    full_main_title = row.get('main_title', 'untitled')
                    match = re.search(r"<span class='highlight'>(.*?)</span>", full_main_title)
                    product_name_for_slug = match.group(1) if match else full_main_title

                    badge_text = row.get('badge', '')
                    sub_title_text = row.get('sub_title', '')

                    combined_text = f"{badge_text} {product_name_for_slug} {sub_title_text}".strip()
                    slug = generate_slug(combined_text)
                    
                    output_filename = f"{slug}.png"
                    
                    # Render the HTML with data from the CSV row
                    rendered_html = render_template_string(html_template_str, **row)
                    
                    # Create the thumbnail
                    asyncio.run(create_thumbnail(rendered_html, output_filename))
                    
                    # Save metadata to DB
                    thumbnail_data = {
                        "id": unique_id,
                        "filename": output_filename,
                        "template": template_name,
                        "data": row,
                        "created_at": os.path.getctime(os.path.join(app.config['GENERATED_FOLDER'], output_filename))
                    }
                    db['thumbnails'].append(thumbnail_data)
            write_db(db)
            flash(f'Successfully generated thumbnails from {filename}!')
        except Exception as e:
            flash(f'An error occurred: {e}')

        return redirect(url_for('index', _anchor='gallery'))

    flash('Invalid file type. Please upload a CSV file.')
    return redirect(url_for('index'))

    return redirect(url_for('index', _anchor='gallery'))

@app.route('/manual')
def manual_entry():
    """Displays the manual column entry page."""
    template_files = os.listdir(app.config['TEMPLATE_FOLDER'])
    templates = sorted([f for f in template_files if f.endswith('.html')])
    return render_template('manual_entry.html', templates=templates)

@app.route('/generate_manual', methods=['POST'])
def generate_manual():
    """Generates thumbnails from four columns of line-separated text."""
    template_name = request.form.get('template')
    if not template_name:
        flash('No template selected.')
        return redirect(url_for('manual_entry'))

    # Get lists of values by splitting the textarea content by lines
    badges = request.form.get('badges', '').splitlines()
    main_titles = request.form.get('main_titles', '').splitlines()
    highlight_words = request.form.get('highlight_words', '').splitlines()
    sub_titles = request.form.get('sub_titles', '').splitlines()
    image_urls = request.form.get('image_urls', '').splitlines()

    # Determine the number of thumbnails to create (use the longest list)
    num_thumbnails = max(len(badges), len(main_titles), len(sub_titles), len(image_urls))

    if num_thumbnails == 0:
        flash('No data entered.')
        return redirect(url_for('manual_entry'))

    template_path = os.path.join(app.config['TEMPLATE_FOLDER'], template_name)
    with open(template_path, 'r') as f:
        html_template_str = f.read()

    db = get_db()
    count = 0
    try:
        for i in range(num_thumbnails):
            # Assemble data for one row, using empty strings for missing lines
            plain_title = main_titles[i] if i < len(main_titles) else ''
            highlight_word = highlight_words[i] if i < len(highlight_words) else ''

            # Automatically create the highlighted title
            if highlight_word and highlight_word in plain_title:
                final_title = plain_title.replace(highlight_word, f"<span class='highlight'>{highlight_word}</span>")
            else:
                final_title = plain_title

            row_data = {
                "badge": badges[i] if i < len(badges) else '',
                "main_title": final_title,
                "sub_title": sub_titles[i] if i < len(sub_titles) else '',
                "image_url": image_urls[i] if i < len(image_urls) else ''
            }

            # Generate a unique ID for the thumbnail record
            unique_id = str(uuid.uuid4())
            
            full_main_title = row_data.get('main_title', 'untitled')
            match = re.search(r"<span class='highlight'>(.*?)</span>", full_main_title)
            product_name_for_slug = match.group(1) if match else full_main_title

            badge_text = row_data.get('badge', '')
            sub_title_text = row_data.get('sub_title', '')

            combined_text = f"{badge_text} {product_name_for_slug} {sub_title_text}".strip()
            slug = generate_slug(combined_text)
            
            output_filename = f"{slug}.png"
            
            rendered_html = render_template_string(html_template_str, **row_data)
            asyncio.run(create_thumbnail(rendered_html, output_filename))
            
            thumbnail_data = {
                "id": unique_id,
                "filename": output_filename,
                "template": template_name,
                "data": row_data,
                "created_at": os.path.getctime(os.path.join(app.config['GENERATED_FOLDER'], output_filename))
            }
            db['thumbnails'].append(thumbnail_data)
            count += 1
        
        write_db(db)
        return jsonify({
            'status': 'success',
            'message': f'Successfully generated {count} thumbnail(s) from manual entry!'
        })
    except Exception as e:
        return jsonify({
            'status': 'error',
            'message': f'An error occurred during generation: {e}'
        }), 500 # Return 500 status code for server error


@app.route('/edit/<thumbnail_id>', methods=['GET'])
def edit_thumbnail(thumbnail_id):
    """Displays the page to edit a thumbnail's data."""
    db = get_db()
    thumbnail = next((item for item in db['thumbnails'] if item['id'] == thumbnail_id), None)
    if not thumbnail:
        flash('Thumbnail not found.')
        return redirect(url_for('index'))
    image_urls = db.get('image_urls', [])
    template_files = os.listdir(app.config['TEMPLATE_FOLDER'])
    templates = [f for f in template_files if f.endswith('.html')]
    return render_template('edit.html', thumbnail=thumbnail, image_urls=image_urls, templates=templates)

@app.route('/update/<thumbnail_id>', methods=['POST'])
def update_thumbnail(thumbnail_id):
    """Updates a thumbnail's data and regenerates the image."""
    db = get_db()
    thumbnail = next((item for item in db['thumbnails'] if item['id'] == thumbnail_id), None)
    if not thumbnail:
        return jsonify({'status': 'error', 'message': 'Thumbnail not found.'}), 404

    # Update data from form
    new_data = request.form.to_dict()
    thumbnail['data'] = new_data
    
    # Handle template change
    new_template = request.form.get('template_select')
    if new_template and new_template != thumbnail['template']:
        thumbnail['template'] = new_template

    # Handle image upload
    if 'image_file' in request.files:
        image_file = request.files['image_file']
        if image_file and image_file.filename != '' and allowed_file(image_file.filename):
            image_filename = secure_filename(f"{thumbnail_id}_{image_file.filename}")
            image_path = os.path.join(app.config['IMAGE_UPLOAD_FOLDER'], image_filename)
            image_file.save(image_path)
            # Update the image_url to point to the local file
            thumbnail['data']['image_url'] = url_for('uploaded_image', filename=image_filename)

    # Regenerate thumbnail
    template_path = os.path.join(app.config['TEMPLATE_FOLDER'], thumbnail['template'])
    with open(template_path, 'r') as f:
        html_template_str = f.read()
    
    rendered_html = render_template_string(html_template_str, **thumbnail['data'])
    asyncio.run(create_thumbnail(rendered_html, thumbnail['filename']))

    write_db(db)
    
    # Return JSON response for AJAX
    return jsonify({
        'status': 'success',
        'message': 'Thumbnail updated successfully!',
        'new_image_url': url_for('generated_file', filename=thumbnail['filename'], _external=True) + f'?v={uuid.uuid4()}' # Add cache-buster
    })

@app.route('/delete/<thumbnail_id>', methods=['POST'])
def delete_thumbnail(thumbnail_id):
    """Deletes a thumbnail image and its database record."""
    db = get_db()
    thumbnail = next((item for item in db['thumbnails'] if item['id'] == thumbnail_id), None)
    if not thumbnail:
        flash('Thumbnail not found.')
        return redirect(url_for('index'))

    # Delete image file
    try:
        os.remove(os.path.join(app.config['GENERATED_FOLDER'], thumbnail['filename']))
    except OSError as e:
        flash(f"Error deleting file: {e}")

    # Remove from DB
    db['thumbnails'] = [item for item in db['thumbnails'] if item['id'] != thumbnail_id]
    write_db(db)
    
    flash('Thumbnail deleted.')
    return redirect(url_for('index'))


@app.route('/library/save/<thumbnail_id>', methods=['POST'])
def save_to_library(thumbnail_id):
    db = load_db()
    thumbnail_to_save = next((t for t in db['thumbnails'] if t['id'] == thumbnail_id), None)

    if thumbnail_to_save:
        if 'library' not in db:
            db['library'] = {'folders': [], 'images': []}
        
        # Check if the image is already in the library
        if not any(img['id'] == thumbnail_id for img in db['library']['images']):
            db['library']['images'].append(thumbnail_to_save)
            save_db(db)
            flash('Thumbnail saved to library.', 'success')
        else:
            flash('Thumbnail is already in the library.', 'info')
    else:
    return redirect(url_for('index'))

@app.route('/library')
def library():
    db = load_db()
    library_images = db.get('library', {}).get('images', [])
    templates = get_templates()
    return render_template('library.html', library_images=library_images, templates=templates)

@app.route('/library/delete/<thumbnail_id>', methods=['POST'])
def delete_from_library(thumbnail_id):
    db = load_db()
    if 'library' in db and 'images' in db['library']:
        db['library']['images'] = [img for img in db['library']['images'] if img['id'] != thumbnail_id]
        save_db(db)
        flash('Thumbnail removed from library.', 'success')
    else:
        flash('Library not found or is empty.', 'error')
    return redirect(url_for('library'))

@app.route('/generated/<filename>')
def generated_file(filename):
    """Serves a generated thumbnail image."""
    return send_from_directory(app.config['GENERATED_FOLDER'], filename)

@app.route('/download_template')
def download_template():
    """Serves the sample CSV template file."""
    return send_from_directory('.', 'template.csv', as_attachment=True, mimetype='text/csv', download_name='template.csv')

@app.route('/upload_template', methods=['POST'])
def upload_template():
    """Handles uploading of new HTML thumbnail templates."""
    if 'file' not in request.files:
        flash('No file part')
        return redirect(url_for('index'))
    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('index'))
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['TEMPLATE_FOLDER'], filename))
        flash('Template uploaded successfully!')
    else:
        flash('Invalid file type. Please upload an HTML file.')
    return redirect(url_for('index'))

@app.route('/download_all')
def download_all():
    """Creates a zip file of all thumbnails and sends it."""
    db = get_db()
    if not db['thumbnails']:
        flash("No thumbnails to download.")
        return redirect(url_for('index'))

    zip_filename = f"thumbnails_{uuid.uuid4()}.zip"
    zip_filepath = os.path.join(app.config['UPLOAD_FOLDER'], zip_filename)

    with zipfile.ZipFile(zip_filepath, 'w') as zipf:
        for thumbnail in db['thumbnails']:
            image_path = os.path.join(app.config['GENERATED_FOLDER'], thumbnail['filename'])
            if os.path.exists(image_path):
                zipf.write(image_path, arcname=thumbnail['filename'])
    
    return send_from_directory(app.config['UPLOAD_FOLDER'], zip_filename, as_attachment=True)


@app.route('/templates')
def manage_templates():
    """Displays the template editor page."""
    template_files = os.listdir(app.config['TEMPLATE_FOLDER'])
    templates = sorted([f for f in template_files if f.endswith('.html')])
    return render_template('manage_templates.html', templates=templates)

@app.route('/templates/get/<path:filename>')
def get_template_content(filename):
    """Returns the content of a specific template file as JSON."""
    # Basic security check
    if '..' in filename or not filename.endswith('.html'):
        return {"error": "Invalid filename"}, 400
    
    filepath = os.path.join(app.config['TEMPLATE_FOLDER'], filename)
    if not os.path.exists(filepath):
        return {"error": "File not found"}, 404
        
    with open(filepath, 'r') as f:
        content = f.read()
    return {"content": content}

@app.route('/templates/save', methods=['POST'])
def save_template():
    """Saves content to a template file."""
    filename = request.form.get('filename')
    content = request.form.get('content')

    if not filename or not content:
        flash('Filename and content are required.')
        return redirect(url_for('manage_templates'))

    # Sanitize filename for security
    secure_name = secure_filename(filename)
    if not secure_name.endswith('.html'):
        secure_name += '.html'

    filepath = os.path.join(app.config['TEMPLATE_FOLDER'], secure_name)
    
    try:
        with open(filepath, 'w') as f:
            f.write(content)
        flash(f'Template "{secure_name}" saved successfully!')
    except Exception as e:
        flash(f'Error saving template: {e}')

    return redirect(url_for('manage_templates', highlight_file=secure_name))


@app.route('/templates/upload', methods=['POST'])
def upload_template_file():
    """Handles uploading of new HTML template files from the editor page."""
    if 'file' not in request.files:
        flash('No file part')
        return redirect(url_for('manage_templates'))
    file = request.files['file']
    if file.filename == '':
        flash('No selected file')
        return redirect(url_for('manage_templates'))
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        file.save(os.path.join(app.config['TEMPLATE_FOLDER'], filename))
        flash(f'Template "{filename}" uploaded successfully!')
    else:
        flash('Invalid file type. Please upload an HTML file.')
    return redirect(url_for('manage_templates', highlight_file=filename))


@app.route('/clear_all', methods=['POST'])
def clear_all():
    """Deletes all thumbnails and clears the database."""
    db = get_db()
    for thumbnail in db['thumbnails']:
        try:
            os.remove(os.path.join(app.config['GENERATED_FOLDER'], thumbnail['filename']))
        except OSError:
            pass # Ignore if file doesn't exist
    
    db['thumbnails'] = []
    write_db(db)
    flash('All thumbnails have been cleared.')
    return redirect(url_for('index', _anchor='gallery'))


@app.route('/bulk_swap', methods=['POST'])
def bulk_swap():
    """Applies a single template to all existing thumbnails."""
    new_template = request.form.get('template')
    if not new_template:
        flash('No template selected for bulk swap.')
        return redirect(url_for('index'))

    db = get_db()
    if not db['thumbnails']:
        flash('No thumbnails to apply changes to.')
        return redirect(url_for('index'))

    template_path = os.path.join(app.config['TEMPLATE_FOLDER'], new_template)
    with open(template_path, 'r') as f:
        html_template_str = f.read()

    for thumbnail in db['thumbnails']:
        thumbnail['template'] = new_template
        rendered_html = render_template_string(html_template_str, **thumbnail['data'])
        asyncio.run(create_thumbnail(rendered_html, thumbnail['filename']))
    
    write_db(db)
    flash(f'All thumbnails have been updated to the "{new_template}" design.')
    return redirect(url_for('index', _anchor='gallery'))


@app.route('/swap_template/<thumbnail_id>', methods=['POST'])
def swap_template(thumbnail_id):
    """Swaps the template for a thumbnail and regenerates it."""
    db = get_db()
    thumbnail = next((item for item in db['thumbnails'] if item['id'] == thumbnail_id), None)
    if not thumbnail:
        flash('Thumbnail not found.')
        return redirect(url_for('index'))

    new_template = request.form.get('new_template')
    if not new_template or not os.path.exists(os.path.join(app.config['TEMPLATE_FOLDER'], new_template)):
        flash('Invalid template selected.')
        return redirect(url_for('index'))

    thumbnail['template'] = new_template

    # Regenerate thumbnail
    template_path = os.path.join(app.config['TEMPLATE_FOLDER'], new_template)
    with open(template_path, 'r') as f:
        html_template_str = f.read()
    
    rendered_html = render_template_string(html_template_str, **thumbnail['data'])
    asyncio.run(create_thumbnail(rendered_html, thumbnail['filename']))

    write_db(db)
    # flash(f'Design swapped to {new_template} successfully!') # Flash messages are for redirects
    # return redirect(url_for('index', highlight=thumbnail_id))
    return jsonify({
        'status': 'success',
        'message': f'Design swapped to {new_template} successfully!',
        'new_image_url': url_for('generated_file', filename=thumbnail['filename'], _external=True) + f'?v={uuid.uuid4()}' # Add cache-buster
    })


@app.route('/bulk_edit_text', methods=['POST'])
def bulk_edit_text():
    """Applies new text to all existing thumbnails."""
    new_badge = request.form.get('badge')
    new_main_title_format = request.form.get('main_title')
    new_sub_title = request.form.get('sub_title')

    if not new_badge and not new_main_title_format and not new_sub_title:
        flash('No text entered for bulk edit.')
        return redirect(url_for('index'))

    db = get_db()
    if not db['thumbnails']:
        flash('No thumbnails to apply changes to.')
        return redirect(url_for('index'))

    for thumbnail in db['thumbnails']:
        if new_badge:
            thumbnail['data']['badge'] = new_badge
        
        if new_main_title_format:
            if '{product_name}' in new_main_title_format:
                # Extract product name from old title
                old_main_title = thumbnail['data'].get('main_title', '')
                match = re.search(r"<span class='highlight'>(.*?)</span>", old_main_title)
                if match:
                    product_name = match.group(1)
                    # Create new title with placeholder replaced
                    new_title = new_main_title_format.replace('{product_name}', f"<span class='highlight'>{product_name}</span>")
                    thumbnail['data']['main_title'] = new_title
                else:
                    # If no highlight found, just replace the placeholder with an empty string
                    thumbnail['data']['main_title'] = new_main_title_format.replace('{product_name}', '')
            else:
                thumbnail['data']['main_title'] = new_main_title_format

        if new_sub_title:
            thumbnail['data']['sub_title'] = new_sub_title

        # Regenerate thumbnail
        template_path = os.path.join(app.config['TEMPLATE_FOLDER'], thumbnail['template'])
        with open(template_path, 'r') as f:
            html_template_str = f.read()
        
        rendered_html = render_template_string(html_template_str, **thumbnail['data'])
        asyncio.run(create_thumbnail(rendered_html, thumbnail['filename']))
    
    write_db(db)
    flash(f'All thumbnails have been updated with the new text.')
    return redirect(url_for('index', _anchor='gallery'))


@app.route('/spin_images', methods=['POST'])
def spin_images():
    """Randomly assigns an image from the saved URLs to each thumbnail."""
    db = get_db()
    image_urls = db.get('image_urls', [])
    if not image_urls:
        flash('No image URLs saved. Please add some in Settings.', 'error')
        return redirect(url_for('index'))

    thumbnails = db.get('thumbnails', [])
    if not thumbnails:
        flash('No thumbnails to apply images to.', 'error')
        return redirect(url_for('index'))

    for thumbnail in thumbnails:
        thumbnail['data']['image_url'] = random.choice(image_urls)
        
        template_path = os.path.join(app.config['TEMPLATE_FOLDER'], thumbnail['template'])
        with open(template_path, 'r') as f:
            html_template_str = f.read()
        
        rendered_html = render_template_string(html_template_str, **thumbnail['data'])
        asyncio.run(create_thumbnail(rendered_html, thumbnail['filename']))

    write_db(db)
    # flash('All thumbnail images have been randomly updated!', 'success')
    # return redirect(url_for('index', _anchor='gallery'))
    return jsonify({
        'status': 'success',
        'message': 'All thumbnail images have been randomly updated!'
    })

@app.route('/spin_thumbnail/<thumbnail_id>', methods=['POST'])
def spin_thumbnail(thumbnail_id):
    """Randomly assigns an image from the saved URLs to a specific thumbnail."""
    db = get_db()
    image_urls = db.get('image_urls', [])
    if not image_urls:
        return jsonify({'status': 'error', 'message': 'No image URLs saved. Please add some in Settings.'}), 400

    thumbnail = next((item for item in db['thumbnails'] if item['id'] == thumbnail_id), None)
    if not thumbnail:
        return jsonify({'status': 'error', 'message': 'Thumbnail not found.'}), 404

    try:
        thumbnail['data']['image_url'] = random.choice(image_urls)
        
        template_path = os.path.join(app.config['TEMPLATE_FOLDER'], thumbnail['template'])
        with open(template_path, 'r') as f:
            html_template_str = f.read()
        
        rendered_html = render_template_string(html_template_str, **thumbnail['data'])
        asyncio.run(create_thumbnail(rendered_html, thumbnail['filename']))

        write_db(db)
        return jsonify({
            'status': 'success',
            'message': 'Thumbnail image randomly updated!',
            'new_image_url': url_for('generated_file', filename=thumbnail['filename'], _external=True) + f'?v={uuid.uuid4()}' # Add cache-buster
        })
    except Exception as e:
        return jsonify({'status': 'error', 'message': f'An error occurred: {e}'}), 500


if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=8080)


