import struct, os, sys, time, select

def main():
    options = [
        "Full Install (Recommended)",
        "Browser Only (No Theme)",
        "Theme Only",
        "Uninstall Everything",
        "Uninstall Browser Only",
        "Uninstall Theme Only",
        "Exit"
    ]
    
    selected = 0
    js = None
    
    try:
        # Open in non-blocking mode to avoid hangs
        js_fd = os.open('/dev/input/js0', os.O_RDONLY | os.O_NONBLOCK)
        js = os.fdopen(js_fd, 'rb')
    except Exception as e:
        # Log to stderr so user can see why it failed
        sys.stderr.write(f"Warning: Could not open /dev/input/js0: {e}\n")
        sys.exit(1)

    def print_menu():
        # Write UI to stderr so it doesn't get captured by choice=$(...)
        sys.stderr.write("\033[H\033[J")
        sys.stderr.write("\033[1m=== Fire4ArkOS Installer ===\033[0m\n\n")
        sys.stderr.write("Use DPAD to move, A to select.\n\n")
        for i, opt in enumerate(options):
            if i == selected:
                sys.stderr.write(f" \033[1;32m-> [{opt}]\033[0m\n")
            else:
                sys.stderr.write(f"    {opt}\n")
        sys.stderr.flush()

    print_menu()
    
    # Simple input loop with select
    while True:
        # Check if data is available on js or stdin
        r, _, _ = select.select([js, sys.stdin], [], [], 0.1)
        
        if js in r:
            data = js.read(8)
            if data and len(data) == 8:
                t, val, type, num = struct.unpack('IhBB', data)
                if type == 1 and val == 1: # Button Down
                    if num == 1: # A button (Select)
                        print(selected + 1)
                        return 0
                    if num == 0: # B button (Back/Exit)
                        print(7)
                        return 0
                    if num == 8: # UP
                        selected = (selected - 1) % len(options)
                        print_menu()
                    if num == 9: # DOWN
                        selected = (selected + 1) % len(options)
                        print_menu()
        
        if sys.stdin in r:
            # Basic keyboard support (1-7 or Enter)
            char = sys.stdin.read(1)
            if char.isdigit():
                val = int(char)
                if 1 <= val <= 7:
                    print(val)
                    return 0
            elif char == '\n':
                print(selected + 1)
                return 0

        time.sleep(0.01)

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
