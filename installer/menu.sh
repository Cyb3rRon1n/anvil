#!/usr/bin/env bash
#
# Anvil's whiptail-driven installer front end - a real bash+whiptail
# Main Menu, DockSTARTer-style. Every choice gathered here is handed
# to the `anvil` CLI, which already has a full --non-interactive --yes
# flag surface - no detection, generation, or validation logic is
# duplicated here, only dialog plumbing and argv-building.
#
# Entry point: `anvil` with no flags (installer/cli.py's main()
# execs this script instead of the TUI). Can also be run directly
# for development: ./installer/menu.sh

set -uo pipefail

ANVIL_BIN="${ANVIL_BIN:-anvil}"
BACKTITLE="Anvil - GPU-Compute Creativity Forge"

# --- Theme ---------------------------------------------------------
#
# whiptail/newt only supports a fixed set of named colors (no
# arbitrary hex) - this is the closest real mapping to the
# cyan-panel / near-black-background / red-selection palette.
export NEWT_COLORS='
root=white,black
border=cyan,black
window=black,cyan
shadow=black,black
title=black,cyan
button=black,cyan
actbutton=white,red
checkbox=black,cyan
actcheckbox=white,red
entry=black,cyan
label=white,black
listbox=black,cyan
actlistbox=white,red
sellistbox=black,cyan
actsellistbox=white,red
textbox=black,cyan
acttextbox=black,cyan
helpline=white,black
roottext=white,black
emptyscale=,black
fullscale=,red
disabledentry=gray,cyan
compactbutton=black,cyan
'

# --- Small helpers ---------------------------------------------------

# In TESTING mode, skip all whiptail dialogs (set TESTING=true to
# exercise the detection/generation path without a terminal).
: "${TESTING:=}"

# Checks the exit status of a whiptail call.  Returns 130 on cancel
# (Escape / Cancel button), aborts on whiptail internal error.
check_exitstatus() {
    case $1 in
        1)   return 130 ;;   # user pressed Cancel / Escape
        255) whiptail --backtitle "$BACKTITLE" --title "Error" \
                 --msgbox "Whiptail error, exiting." 8 60
             exit 1 ;;
    esac
}

# --- Structured logging (Security Onion pattern) --------------------
#
# Every setup step is logged to $setup_log with timestamps and levels.
# In interactive mode the log is silent; on failure it's shown to the user.

SETUP_LOG="${SETUP_LOG:-/tmp/anvil-setup.log}"

log() {
    local msg="$1" level="${2:-INFO}"
    local now
    now=$(date +"%Y-%m-%dT%H:%M:%S%z")
    echo "$now | $level | $msg" >> "$SETUP_LOG" 2>&1
}

log_info()  { log "$1" "INFO"; }
log_error() { log "$1" "ERROR"; }

# Writes a section header to the log (visible in the log file, not on screen).
log_title() {
    echo -e "\n-----------------------------\n $1\n-----------------------------\n" >> "$SETUP_LOG" 2>&1
}

# --- Reads real detected state into the current shell as plain vars.
refresh_detect() {
    eval "$("$ANVIL_BIN" detect)"
}

# whiptail --yesno confirm, then run the given command with real,
# live terminal output. Returns the command's own exit status;
# returns 130 if the user declined the confirm.
confirm_and_run() {
    local title="$1" confirm_text="$2"
    shift 2

    # In TESTING mode, skip the confirm dialog and command execution.
    [ -n "$TESTING" ] && return 0

    if ! whiptail --backtitle "$BACKTITLE" --title "$title" \
        --yesno "$confirm_text" 14 76; then
        return 130
    fi

    clear
    echo "=== $title ==="
    echo

    # `local status` must be declared *before* running "$@", not after -
    # `local` is itself a real command with its own exit status.
    local status
    # ANVIL_PROGRESS=1 turns on the CLI's Rich live progress panel
    # (installer/panel.py) - every menu action keeps its real, live
    # install/docker output on screen inside a progress panel.
    ANVIL_PROGRESS=1 "$@"
    status=$?

    echo
    if [ "$status" -eq 0 ]; then
        echo "Done."
    else
        echo "Failed (exit $status) - see output above."
    fi

    read -rp "Press Enter to return to the menu..." _dummy
    return "$status"
}

# --- Main Menu -------------------------------------------------------

main_menu() {
    while true; do

        CHOICE=$(whiptail --backtitle "$BACKTITLE" --title "Anvil" \
            --menu "Choose an action:" 20 76 5 \
            "guided-setup" "1. Guided Setup - detect GPU, pick tier, generate stack" \
            "start-stack"  "2. Start Stack - docker compose up -d" \
            "stop-stack"   "3. Stop Stack - docker compose down" \
            "view-status"  "4. View Status - show enabled services and URLs" \
            "exit"         "0. Exit" \
            3>&1 1>&2 2>&3)
        status=$?

        if [ "$status" -ne 0 ] || [ "$CHOICE" = "exit" ]; then
            clear
            exit 0
        fi

        case "$CHOICE" in
            guided-setup)
                guided_setup
                ;;
            start-stack)
                start_stack
                ;;
            stop-stack)
                confirm_and_run "Stop Stack" \
                    "This will stop and remove the running stack containers and network." \
                    docker compose -f "stack/docker-compose.yml" down
                ;;
            view-status)
                view_status
                ;;
        esac

    done
}

# --- Guided Setup ----------------------------------------------------
#
# The bash-native equivalent of the TUI's WelcomeScreen ->
# ConfigScreen -> ReviewScreen flow. Ends by handing a single
# fully-formed `anvil --non-interactive --yes ...` invocation to
# confirm_and_run.

guided_setup() {

    # --- Welcome screen (Security Onion pattern) ---
    if [ -z "$TESTING" ]; then
        if ! whiptail --backtitle "$BACKTITLE" --title "Welcome" --yesno \
            "Welcome to the Anvil Setup!\n\nAnvil will detect your GPU and recommend the best\nconfiguration for a local AI/creative stack.\n\nSetup uses keyboard navigation:\n  Arrow keys to move around\n  Enter to select\n  Tab to switch between buttons\n\nWould you like to continue?" 20 76; then
            return 0
        fi
    fi
    log_title "Starting Guided Setup"
    log_info "User entered guided setup"

    # --- Phase 1: Detect ---
    log_title "Phase 1: System Detection"
    refresh_detect
    log_info "GPU: ${GPU_VENDOR:-none} - ${GPU_NAME:-none} (${GPU_VRAM_MB:-0} MB)"
    log_info "Docker: installed=$DOCKER_INSTALLED running=$DOCKER_RUNNING compose=$DOCKER_COMPOSE_V2"
    log_info "Recommended tier: ${RECOMMENDED_TIER:-none}"

    if [ "$DOCKER_INSTALLED" != "true" ] || [ "$DOCKER_RUNNING" != "true" ] || [ "$DOCKER_COMPOSE_V2" != "true" ]; then
        log_info "Docker not fully ready, showing warning"
        if [ -z "$TESTING" ]; then
            whiptail --backtitle "$BACKTITLE" --title "Docker" --msgbox \
                "Docker isn't fully ready yet (installed=$DOCKER_INSTALLED running=$DOCKER_RUNNING compose-v2=$DOCKER_COMPOSE_V2). Continuing will let Anvil try to install/start it for you (--yes is implied)." 12 76
        fi
    fi

    if [ -z "$GPU_VENDOR" ]; then
        log_info "No GPU detected, exiting guided setup"
        if [ -z "$TESTING" ]; then
            whiptail --backtitle "$BACKTITLE" --title "No GPU" --msgbox \
                "No dedicated GPU with real VRAM detected. Anvil has nothing to recommend on this host." 10 70
        fi
        return 0
    fi

    local default_tier="$RECOMMENDED_TIER"
    local gpu_desc="$GPU_VENDOR"
    [ -n "$GPU_NAME" ] && gpu_desc="$GPU_NAME ($GPU_VENDOR)"
    local vram_gb=$(( GPU_VRAM_MB / 1024 ))

    if [ -n "$PREVIOUS_TIER" ]; then
        default_tier="$PREVIOUS_TIER"
    fi

    local light_on medium_on heavy_on
    light_on="OFF"; medium_on="OFF"; heavy_on="OFF"
    case "$default_tier" in
        light) light_on="ON" ;;
        medium) medium_on="ON" ;;
        heavy) heavy_on="ON" ;;
    esac

    # --- Phase 2: Configure ---
    log_title "Phase 2: Configuration"

    # Count how many whiptail steps will actually be shown so we can
    # display [Step N/M] progress on every dialog.
    local total_steps=4  # tier + puid + pgid + start-now are always shown
    if [ "$default_tier" = "heavy" ]; then
        case "$GPU_VENDOR" in
            nvidia|amd|intel) total_steps=$((total_steps + 1)) ;;  # ComfyUI
        esac
        case "$GPU_VENDOR" in
            nvidia|amd) total_steps=$((total_steps + 1)) ;;        # InvokeAI
        esac
    fi
    local step=0

    step=$((step + 1))
    if [ -z "$TESTING" ]; then
        TIER=$(whiptail --backtitle "$BACKTITLE" --title "[Step $step/$total_steps] Choose a Tier" \
            --radiolist "Detected: $gpu_desc, ${vram_gb}GB VRAM.\n$RECOMMENDED_TIER_EXPLANATION" \
            18 76 3 \
            "light"  "Light - small quantized models only" "$light_on" \
            "medium" "Medium - comfortable 7-9B models" "$medium_on" \
            "heavy"  "Heavy - comfortable 14B + image generation" "$heavy_on" \
            3>&1 1>&2 2>&3) || return
    else
        TIER="$default_tier"
    fi

    local COMFYUI_FLAG="--no-comfyui"
    local INVOKEAI_FLAG="--no-invokeai"

    if [ "$TIER" = "heavy" ]; then

        # ComfyUI: supported on all three vendors (nvidia, amd, intel)
        local comfyui_supported=false
        case "$GPU_VENDOR" in
            nvidia|amd|intel) comfyui_supported=true ;;
        esac

        if [ "$comfyui_supported" = true ]; then

            local comfyui_default="ON"
            if [ -n "$PREVIOUS_TIER" ]; then
                [[ ",$PREVIOUS_ENABLED_OPTIONAL," == *",comfyui,"* ]] && comfyui_default="ON" || comfyui_default="OFF"
            fi

            step=$((step + 1))
            if [ -z "$TESTING" ]; then
                if whiptail --backtitle "$BACKTITLE" --title "[Step $step/$total_steps] ComfyUI" \
                    --checklist "Enable ComfyUI (image generation)? Model checkpoints must be placed manually after first start." \
                    12 76 1 \
                    "comfyui" "ComfyUI - node-based image generation" "$comfyui_default" \
                    3>&1 1>&2 2>&3 | grep -q "comfyui"; then
                    COMFYUI_FLAG="--comfyui"
                fi
            else
                [ "$comfyui_default" = "ON" ] && COMFYUI_FLAG="--comfyui"
            fi
        fi

        # InvokeAI: supported on nvidia and amd only (no intel image)
        local invokeai_supported=false
        case "$GPU_VENDOR" in
            nvidia|amd) invokeai_supported=true ;;
        esac

        if [ "$invokeai_supported" = true ]; then

            local invokeai_default="ON"
            if [ -n "$PREVIOUS_TIER" ]; then
                [[ ",$PREVIOUS_ENABLED_OPTIONAL," == *",invokeai,"* ]] && invokeai_default="ON" || invokeai_default="OFF"
            fi

            step=$((step + 1))
            if [ -z "$TESTING" ]; then
                if whiptail --backtitle "$BACKTITLE" --title "[Step $step/$total_steps] InvokeAI" \
                    --checklist "Enable InvokeAI (turnkey image generation)? Models download straight from InvokeAI's built-in Model Manager." \
                    12 76 1 \
                    "invokeai" "InvokeAI - turnkey image generation" "$invokeai_default" \
                    3>&1 1>&2 2>&3 | grep -q "invokeai"; then
                    INVOKEAI_FLAG="--invokeai"
                fi
            else
                [ "$invokeai_default" = "ON" ] && INVOKEAI_FLAG="--invokeai"
            fi
        fi

    fi

    local default_puid_value="$DEFAULT_PUID"
    local default_pgid_value="$DEFAULT_PGID"

    if [ -n "$PREVIOUS_PUID" ]; then
        default_puid_value="$PREVIOUS_PUID"
        default_pgid_value="$PREVIOUS_PGID"
    fi

    if [ -z "$TESTING" ]; then
        step=$((step + 1))
        PUID=$(whiptail --backtitle "$BACKTITLE" --title "[Step $step/$total_steps] User/Group" \
            --inputbox "PUID - user ID the containers run as" 10 70 "$default_puid_value" \
            3>&1 1>&2 2>&3) || return

        step=$((step + 1))
        PGID=$(whiptail --backtitle "$BACKTITLE" --title "[Step $step/$total_steps] User/Group" \
            --inputbox "PGID - group ID the containers run as" 10 70 "$default_pgid_value" \
            3>&1 1>&2 2>&3) || return
    else
        PUID="$default_puid_value"
        PGID="$default_pgid_value"
    fi

    local START_FLAG="--no-start"
    if [ -z "$TESTING" ]; then
        if whiptail --backtitle "$BACKTITLE" --title "Start Now" \
            --yesno "Start the stack now, right after generating it?" 10 70; then
            START_FLAG="--start"
        fi
    else
        START_FLAG="--start"
    fi

    # --- Phase 3: Review & Execute ---
    log_title "Phase 3: Review & Execute"
    log_info "Selected tier: $TIER"
    log_info "ComfyUI: $COMFYUI_FLAG"
    log_info "InvokeAI: $INVOKEAI_FLAG"
    log_info "PUID=$PUID PGID=$PGID"
    log_info "Start: $START_FLAG"

    # Show a full settings summary before executing (Security Onion pattern).
    if [ -z "$TESTING" ]; then
        local summary=""
        summary+="Tier:       $TIER\n"
        summary+="GPU:        $GPU_VENDOR - $GPU_NAME (${vram_gb}GB)\n"
        summary+="PUID/PGID:  $PUID / $PGID\n"
        summary+="ComfyUI:    $([ "$COMFYUI_FLAG" = "--comfyui" ] && echo "yes" || echo "no")\n"
        summary+="InvokeAI:   $([ "$INVOKEAI_FLAG" = "--invokeai" ] && echo "yes" || echo "no")\n"
        summary+="Auto-start: $([ "$START_FLAG" = "--start" ] && echo "yes" || echo "no")\n"
        summary+="\nPress TAB to select yes or no."

        if ! whiptail --backtitle "$BACKTITLE" --title "Review Settings" \
            --yesno "$summary" 20 76 --scrolltext; then
            return 0
        fi
    fi

    confirm_and_run "Guided Setup" \
        "About to generate a $TIER stack (PUID=$PUID PGID=$PGID). Continue?" \
        "$ANVIL_BIN" --non-interactive --yes \
            --tier "$TIER" \
            --puid "$PUID" --pgid "$PGID" \
            $COMFYUI_FLAG $INVOKEAI_FLAG \
            "$START_FLAG"
    local rc=$?

    if [ "$rc" -eq 0 ]; then
        log_info "Guided setup completed successfully"
        if [ -z "$TESTING" ]; then

            if [ "$START_FLAG" = "--start" ]; then

                local urls
                urls=$("$ANVIL_BIN" urls 2>/dev/null)

                local complete_msg="Anvil setup is complete!\n\nYour stack is running."
                [ -n "$urls" ] && complete_msg+="\n\nService URLs:\n$urls"
                complete_msg+="\n\nTo manage your stack:\n  Stop:   docker compose -f stack/docker-compose.yml down\n  Status: docker compose -f stack/docker-compose.yml ps"

                whiptail --backtitle "$BACKTITLE" --title "Setup Complete" \
                    --msgbox "$complete_msg" 22 76 --scrolltext
            else
                whiptail --backtitle "$BACKTITLE" --title "Setup Complete" --msgbox \
                    "Anvil setup is complete!\n\nStack written to stack/docker-compose.yml (not started yet).\n\nStart it when ready:\n  docker compose -f stack/docker-compose.yml up -d" 14 76
            fi
        fi
    else
        log_error "Guided setup failed (exit $rc)"
        if [ -z "$TESTING" ]; then
            whiptail --backtitle "$BACKTITLE" --title "Setup Failed" --msgbox \
                "Setup had a problem (exit $rc).\n\nCheck the log for details:\n$SETUP_LOG" 12 76
        fi
    fi
}

# --- Start Stack -----------------------------------------------------

start_stack() {

    local compose_file="stack/docker-compose.yml"

    if [ ! -f "$compose_file" ]; then
        whiptail --backtitle "$BACKTITLE" --title "Start Stack" --msgbox \
            "No stack found at $compose_file. Run Guided Setup first." 10 70
        return 0
    fi

    confirm_and_run "Start Stack" \
        "This will start the stack using $compose_file." \
        docker compose -f "$compose_file" up -d
}

# --- View Status -----------------------------------------------------

view_status() {

    local compose_file="stack/docker-compose.yml"

    if [ ! -f "$compose_file" ]; then
        whiptail --backtitle "$BACKTITLE" --title "View Status" --msgbox \
            "No stack found at $compose_file. Run Guided Setup first." 10 70
        return 0
    fi

    local status_text="Stack: $compose_file\n\n"

    if grep -q "ollama" "$compose_file" 2>/dev/null; then
        status_text+="Ollama:     http://localhost:11434\n"
    fi
    if grep -q "open-webui" "$compose_file" 2>/dev/null; then
        status_text+="Open WebUI: http://localhost:3000\n"
    fi
    if grep -q "comfyui" "$compose_file" 2>/dev/null; then
        status_text+="ComfyUI:    http://localhost:8188\n"
    fi
    if grep -q "invokeai" "$compose_file" 2>/dev/null; then
        status_text+="InvokeAI:   http://localhost:9090\n"
    fi
    if grep -q "dashboard" "$compose_file" 2>/dev/null; then
        status_text+="Dashboard:  http://localhost:8080\n"
    fi

    whiptail --backtitle "$BACKTITLE" --title "View Status" \
        --msgbox "$status_text" 16 70
}

# --- Entry point -----------------------------------------------------

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then

    if ! command -v whiptail >/dev/null 2>&1; then
        echo "whiptail is required but not installed. Install it (e.g. 'sudo apt install whiptail' or 'sudo dnf install newt') and try again." >&2
        exit 1
    fi

    # Preserve old log on each run (Security Onion pattern).
    [ -f "$SETUP_LOG" ] && mv "$SETUP_LOG" "$SETUP_LOG.$(date +%Y%m%d%H%M%S)" 2>/dev/null

    # Trap unhandled errors — show the failed screen before exiting.
    trap 'log_error "Unhandled error on line $LINENO"; whiptail --backtitle "$BACKTITLE" --title "Error" --msgbox "Unexpected error. Check log:\n$SETUP_LOG" 10 76 2>/dev/null; exit 1' ERR

    # First run (no stack yet) skips the Main Menu entirely and drops
    # straight into Guided Setup, matching Security Onion's so-setup -
    # a single linear wizard, not a menu to pick from. The Main Menu
    # only appears once a stack exists, for the real day-2 operations
    # (start/stop/status) so-setup's own one-shot model never needed.
    refresh_detect

    if [ "$STACK_EXISTS" = "true" ]; then
        main_menu
    else
        guided_setup
    fi
fi
