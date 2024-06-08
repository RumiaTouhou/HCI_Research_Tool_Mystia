import json
import os
import datetime
import threading
from pynput import mouse, keyboard
from PIL import ImageGrab
import pygetwindow as gw
import time
from collections import deque
import keyboard

# Constants and global variables
THRESHOLD_TIME = 0.15  # seconds
DISTANCE_THRESHOLD = 4  # units in pixels
WINDOW_TITLE_DELAY = 0.1  # seconds to wait before re-checking window title
session_active = False
event_thread = None
data_store = []
start_time = None
screenshot_folder = ""
window_title_buffer = deque(maxlen=5)  # Buffer to store recent window title changes
recorded_window_titles = set()  # Set to store recorded window titles
initial_window_title = None  # To store the initial foreground window title
total_duration = None  # To store the total duration of the program

# Get the directory where the script is located
base_directory = os.path.dirname(os.path.abspath(__file__))

# Mapping of invalid characters to valid substitutes
INVALID_CHAR_MAPPING = {
    '#': 'SHARP',
    '\\': 'BACKSLASH',
    '/': 'SLASH',
    ':': 'COLON',
    '*': 'ASTERISK',
    '?': 'QUESTION',
    '"': 'QUOTE',
    '<': 'LESS',
    '>': 'GREATER',
    '|': 'PIPE'
}

def calculate_distance(start_pos, end_pos):
    """Calculate the Euclidean distance between two points."""
    return ((end_pos[0] - start_pos[0]) ** 2 + (end_pos[1] - start_pos[1]) ** 2) ** 0.5

def format_time_since(start):
    """Format the current time since start to a floating-point number in seconds."""
    return (datetime.datetime.now() - start).total_seconds()

def get_foreground_window_title():
    """Get the title of the current active window."""
    retries = 3
    for _ in range(retries):
        try:
            active_window = gw.getActiveWindow()
            if active_window and active_window.title != "":
                return active_window.title
            else:
                time.sleep(0.1)  # Wait and retry
        except Exception as e:
            time.sleep(0.1)
    return "Unknown"

def save_data_to_json():
    """Save the recorded data to a JSON file named after the session start time."""
    global data_store, start_time, total_duration, initial_window_title
    filename = os.path.join(base_directory, f"{start_time.strftime('%Y-%m-%d-%H-%M-%S')}.json")
    data = {
        "session_start_time": start_time.isoformat(),
        "total_duration": total_duration,
        "initial_foreground_window_title": initial_window_title,
        "actions": data_store
    }
    with open(filename, 'w', encoding='utf-8') as file:
        json.dump(data, file, indent=4, ensure_ascii=False)
    print(f"Data saved to {filename}")

mouse_data = {}  # Initialize the dictionary to store mouse event state
last_window_title = None
click_buffer = deque()  # Queue to store click events temporarily

def sanitize_window_title(window_title):
    """Replace invalid characters in the window title with valid substitutes."""
    for invalid_char, substitute in INVALID_CHAR_MAPPING.items():
        window_title = window_title.replace(invalid_char, substitute)
    return window_title

def get_current_window_title():
    """Fetch the current window title, retrying if necessary."""
    for _ in range(3):
        title = get_foreground_window_title()
        if title != "Unknown":
            return title
        time.sleep(0.05)
    return "Unknown"

def process_click_event(event):
    """Process a buffered click event, ensuring correct window title assignment."""
    # Introduce a delay to allow window title to update
    time.sleep(WINDOW_TITLE_DELAY)
    
    # Re-check window title until it's not "Unknown"
    title = get_current_window_title()
    while title == "Unknown":
        time.sleep(0.05)
        title = get_current_window_title()
    
    # Assign the correct window title to the click event
    event['window_title'] = title
    data_store.append(event)
    print(f"Recorded {event['click_type']}: {event}")

    # Take screenshot if the title is new
    if title not in recorded_window_titles:
        screenshot_path = take_screenshot(title)
        print(f"Screenshot taken: {screenshot_path}")
        recorded_window_titles.add(title)

def on_click(x, y, button, pressed):
    global start_time, data_store, last_window_title, window_title_buffer, mouse_data, session_active, click_buffer
    if not session_active:
        return  # Exit early if session is not active

    current_time = format_time_since(start_time)

    if pressed:
        # Record the start details of the click
        mouse_data['start_time'] = current_time
        mouse_data['start_pos'] = (x, y)
        mouse_data['button'] = button
    else:
        # Calculate duration and distance
        duration = current_time - mouse_data['start_time']
        distance_x = abs(mouse_data['start_pos'][0] - x)
        distance_y = abs(mouse_data['start_pos'][1] - y)
        action_type = 'drag' if duration >= THRESHOLD_TIME and (distance_x >= DISTANCE_THRESHOLD or distance_y >= DISTANCE_THRESHOLD) else 'click'
        click_type = 'right' if button == mouse.Button.right else 'left'
        full_action_type = f"{click_type}_{action_type}"

        click_event = {
            "click_index": len(data_store) + 1,
            "click_type": full_action_type,
            "type_click_index": sum(1 for action in data_store if action['click_type'] == full_action_type) + 1,
            "window_title": "Unknown",  # Initially set to "Unknown"
            "click_time": current_time if action_type == 'click' else None,
            "start_time": mouse_data['start_time'] if action_type == 'drag' else None,
            "end_time": current_time if action_type == 'drag' else None,
            "start_coordinates": mouse_data['start_pos'] if action_type == 'drag' else None,
            "end_coordinates": {'x': x, 'y': y} if action_type == 'drag' else None,
            "click_coordinates": {'x': x, 'y': y} if action_type == 'click' else None
        }

        # Buffer the click event
        click_buffer.append(click_event)

        # Process the buffered click event
        process_click_event(click_event)

def take_screenshot(window_title):
    """Take a screenshot and save it to the designated folder."""
    sanitized_title = sanitize_window_title(window_title)
    if not sanitized_title or sanitized_title == "Unknown":
        return "Invalid filename"

    screenshot_path = os.path.join(screenshot_folder, f"{sanitized_title}.png")
    try:
        ImageGrab.grab().save(screenshot_path)
        return screenshot_path
    except Exception as e:
        return "Error"

def start_recording():
    global start_time, session_active, screenshot_folder, event_thread, initial_window_title
    if not session_active:
        start_time = datetime.datetime.now()
        session_active = True
        screenshot_folder = os.path.join(base_directory, f"Screenshots - {start_time.strftime('%Y-%m-%d-%H-%M-%S')}")
        os.makedirs(screenshot_folder, exist_ok=True)
        print("Program activated! Record starts. Press Ctrl + Down to terminate this program")
        
        # Capture initial window title and take screenshot
        initial_window_title = get_foreground_window_title()
        print(f"Initial foreground window title: {initial_window_title}")
        screenshot_path = take_screenshot(initial_window_title)
        print(f"Screenshot taken: {screenshot_path}")
        recorded_window_titles.add(initial_window_title)
        
        event_thread = threading.Thread(target=run_mouse_listener)
        event_thread.start()
        window_title_thread = threading.Thread(target=monitor_window_title)
        window_title_thread.start()

def stop_recording():
    global session_active, event_thread, total_duration
    if session_active:
        session_active = False
        total_duration = format_time_since(start_time)
        save_data_to_json()
        print("Program closed. All records are saved.")
        if event_thread.is_alive():
            event_thread.join()
        # Exit the program
        os._exit(0)

def run_mouse_listener():
    """Start the mouse listener to handle click and drag events."""
    with mouse.Listener(on_click=on_click) as listener:
        listener.join()

def monitor_window_title():
    """Monitor the active window title and log changes with timestamps."""
    global session_active, start_time, last_window_title, window_title_buffer
    while session_active:
        current_window_title = get_foreground_window_title()
        current_time = format_time_since(start_time)
        if current_window_title != last_window_title:
            last_window_title = current_window_title
            window_title_buffer.append((current_time, current_window_title))
        time.sleep(0.05)

def bind_keyboard_shortcuts():
    """Bind keyboard shortcuts for activating and terminating the program using the 'keyboard' library."""
    keyboard.add_hotkey('ctrl+up', start_recording)
    keyboard.add_hotkey('ctrl+down', stop_recording)

def main():
    print("Program starts. Press Ctrl + Up to activate the program.")
    bind_keyboard_shortcuts()
    while session_active or threading.active_count() > 1:
        time.sleep(1)

if __name__ == "__main__":
    main()
