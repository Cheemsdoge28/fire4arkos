import struct, os, sys, time

def get_input(js):
    # Read 8 bytes: time(4), value(2), type(1), number(1)
    data = js.read(8)
    if not data: return None
    t, val, type, num = struct.unpack('IhBB', data)
    
    if type == 1 and val == 1: # Button Down
        if num == 1: return 'ENTER' # A button
        if num == 0: return 'BACK'  # B button
        if num == 8: return 'UP'
        if num == 9: return 'DOWN'
    return None

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
    
    try:
        js = open('/dev/input/js0', 'rb')
    except:
        # Fallback to stdin if no joystick
        print("No controller found. Use keyboard or wait for timeout.")
        return 1

    def print_menu():
        # Clear screen (ANSI escape)
        sys.stdout.write("\033[H\033[J")
        sys.stdout.write("\033[1m=== Fire4ArkOS Installer ===\033[0m\n\n")
        sys.stdout.write("Use DPAD to move, A to select.\n\n")
        for i, opt in enumerate(options):
            if i == selected:
                sys.stdout.write(f" \033[1;32m-> [{opt}]\033[0m\n")
            else:
                sys.stdout.write(f"    {opt}\n")
        sys.stdout.flush()

    print_menu()
    
    while True:
        inp = get_input(js)
        if inp == 'UP':
            selected = (selected - 1) % len(options)
            print_menu()
        elif inp == 'DOWN':
            selected = (selected + 1) % len(options)
            print_menu()
        elif inp == 'ENTER':
            # Output choice index (1-based) to stdout for bash
            print(selected + 1)
            return 0
        elif inp == 'BACK':
            # Exit
            print(len(options))
            return 0
        time.sleep(0.01)

if __name__ == '__main__':
    sys.exit(main())
