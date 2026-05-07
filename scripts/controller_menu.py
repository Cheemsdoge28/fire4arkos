import struct, os, sys, time, select

def main():
    # If an argument is provided, use it as the output file path
    output_file = sys.argv[1] if len(sys.argv) > 1 else None
    
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
        # Log to stderr if no joystick
        sys.stderr.write(f"Warning: Could not open /dev/input/js0: {e}\n")
        sys.exit(1)

    def print_menu():
        # Clear screen and print UI to stdout
        sys.stdout.write("\033[H\033[J")
        sys.stdout.write("\033[1m=== Fire4ArkOS Installer ===\033[0m\n\n")
        sys.stdout.write("Use DPAD to move, A to select.\n\n")
        for i, opt in enumerate(options):
            if i == selected:
                sys.stdout.write(f" \033[1;32m-> [{opt}]\033[0m\n")
            else:
                sys.stdout.write(f"    {opt}\n")
        sys.stdout.flush()

    def finish(choice):
        if output_file:
            with open(output_file, 'w') as f:
                f.write(str(choice))
        else:
            # Fallback for manual testing
            print(choice)
        return 0

    print_menu()
    
    while True:
        # Check if data is available on js or stdin
        r, _, _ = select.select([js, sys.stdin], [], [], 0.1)
        
        if js in r:
            data = js.read(8)
            if data and len(data) == 8:
                t, val, type, num = struct.unpack('IhBB', data)
                if type == 1 and val == 1: # Button Down
                    if num == 1: # A button (Select)
                        return finish(selected + 1)
                    if num == 0: # B button (Back/Exit)
                        return finish(7)
                    if num == 8: # UP
                        selected = (selected - 1) % len(options)
                        print_menu()
                    if num == 9: # DOWN
                        selected = (selected + 1) % len(options)
                        print_menu()
        
        if sys.stdin in r:
            char = sys.stdin.read(1)
            if char.isdigit():
                val = int(char)
                if 1 <= val <= 7:
                    return finish(val)
            elif char == '\n':
                return finish(selected + 1)

        time.sleep(0.01)

if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(1)
