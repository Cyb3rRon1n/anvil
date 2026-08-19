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
# arbitrary hex) - "blue" is the closest named match to Anvil's real
# brand accent, "temper" (#2f97f0 in docs/images/logo.svg and the
# website), so the installer now reads as the same project as its own
# README/site instead of an arbitrary whiptail-safe cyan. Structurally
# still Vulcan's palette inverted (dark panel on a near-black
# background instead of a bright panel on black) - every fg,bg pair
# below is Vulcan's swapped to bg,fg, so the same relative contrast
# between elements holds and the two installers still read as
# deliberately differentiated, just in Anvil's own real hue now.
#
# button/checkbox/listbox originally used the same color for BOTH
# their focused and unfocused state - identical to window's own
# background, so an unfocused Yes/No button (or unselected list row)
# was visually indistinguishable from empty dialog space; red for the
# focused state also didn't reliably show up on some terminal color
# profiles. Same real bug found and fixed in Vulcan's identical theme
# block - every interactive element gets its own visible box at rest
# and a yellow highlight when focused.
export NEWT_COLORS='
root=white,black
border=black,blue
window=blue,black
shadow=black,black
title=blue,black
button=black,blue
actbutton=yellow,black
checkbox=black,blue
actcheckbox=yellow,black
entry=blue,black
label=white,black
listbox=black,blue
actlistbox=yellow,black
sellistbox=black,blue
actsellistbox=yellow,black
textbox=blue,black
acttextbox=blue,black
helpline=white,black
roottext=white,black
emptyscale=black,
fullscale=red,
disabledentry=blue,gray
compactbutton=black,blue
'

# whiptail defaults to "compact" Yes/No/OK/Cancel buttons - plain
# "<Yes>"/"<No>" text with no focused-state color of their own (there's
# no actcompactbutton in newt's colorset list, only actbutton/actcheckbox/
# actlistbox/etc. for other widgets) - so no matter what button/actbutton
# above are set to, Tab/arrow-key focus between Yes and No is never
# visible. --fullbuttons renders real boxed buttons that DO use
# button/actbutton, restoring a visible focus indicator. Same real bug
# and fix as Vulcan's identical theme block.
#
# Only define this if nothing already has - tests/test_menu.bats
# exports its own `whiptail` mock function (real dialogs can't run
# without a terminal) to intercept every call in this script; an
# unconditional definition here would silently override that mock
# with the real binary instead, breaking every test relying on the
# mock's recorded output (confirmed the hard way in Vulcan's identical
# fix, see its own commit history).
if ! declare -F whiptail >/dev/null; then
    whiptail() {
        command whiptail --fullbuttons "$@"
    }
fi

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
            --menu "Choose an action:" 22 76 9 \
            "guided-setup"    "1. Guided Setup - detect GPU, pick tier, generate stack" \
            "start-stack"     "2. Start Stack - docker compose up -d" \
            "stop-stack"      "3. Stop Stack - docker compose down" \
            "update-stack"    "4. Update Stack - pull latest images, recreate containers" \
            "view-status"     "5. View Status - show enabled services and URLs" \
            "backup-stack"    "6. Backup Stack - archive compose/state to backups/" \
            "restore-stack"   "7. Restore Stack - from the most recent backup" \
            "uninstall-stack" "8. Uninstall Stack - delete config, keep downloaded models" \
            "exit"            "0. Exit" \
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
            update-stack)
                confirm_and_run "Update Stack" \
                    "This will pull the latest images and recreate containers." \
                    "$ANVIL_BIN" update --non-interactive --yes
                ;;
            view-status)
                view_status
                ;;
            backup-stack)
                confirm_and_run "Backup Stack" \
                    "This will archive docker-compose.yml and the state file to backups/." \
                    "$ANVIL_BIN" backup
                ;;
            restore-stack)
                confirm_and_run "Restore Stack" \
                    "This will stop the running stack and restore docker-compose.yml and the state file from the most recent backup." \
                    "$ANVIL_BIN" restore --non-interactive --yes
                ;;
            uninstall-stack)
                uninstall_flow
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
        log_info "No GPU detected - Light tier only (CPU-only services)"
    fi

    local default_tier="$RECOMMENDED_TIER"
    local gpu_desc="${GPU_VENDOR:-none detected (CPU-only)}"
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
    local total_steps=11  # tier + puid + pgid + start-now + RAG + Voice + n8n + LiteLLM + SearXNG + Vane + LocalAI are always shown
    if [ "$default_tier" = "heavy" ]; then
        case "$GPU_VENDOR" in
            nvidia|amd|intel) total_steps=$((total_steps + 1)) ;;  # ComfyUI
        esac
        case "$GPU_VENDOR" in
            nvidia|amd) total_steps=$((total_steps + 1)) ;;        # InvokeAI
        esac
    fi
    [ "${VULCAN_STACK_FOUND:-false}" = "true" ] && total_steps=$((total_steps + 1))  # Vulcan integration confirm
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

    # RAG/voice/n8n are CPU-only and vendor-agnostic - offered at every
    # tier, unlike ComfyUI/InvokeAI above which are gated to Heavy and
    # GPU vendor. Same previous-state-aware, defaults-on pattern.
    local RAG_FLAG="--no-rag"
    local rag_default="ON"
    if [ -n "$PREVIOUS_TIER" ]; then
        [[ ",$PREVIOUS_ENABLED_OPTIONAL," == *",qdrant,"* ]] && rag_default="ON" || rag_default="OFF"
    fi
    step=$((step + 1))
    if [ -z "$TESTING" ]; then
        if whiptail --backtitle "$BACKTITLE" --title "[Step $step/$total_steps] RAG" \
            --checklist "Enable RAG (Qdrant + a text-embeddings service)? Lets Open WebUI retrieve answers from documents you upload - needs a one-time admin-panel setting after first start." \
            12 76 1 \
            "rag" "Qdrant + embeddings - document retrieval for Open WebUI" "$rag_default" \
            3>&1 1>&2 2>&3 | grep -q "rag"; then
            RAG_FLAG="--rag"
        fi
    else
        [ "$rag_default" = "ON" ] && RAG_FLAG="--rag"
    fi

    local VOICE_FLAG="--no-voice"
    local voice_default="ON"
    if [ -n "$PREVIOUS_TIER" ]; then
        [[ ",$PREVIOUS_ENABLED_OPTIONAL," == *",whisper,"* ]] && voice_default="ON" || voice_default="OFF"
    fi
    step=$((step + 1))
    if [ -z "$TESTING" ]; then
        if whiptail --backtitle "$BACKTITLE" --title "[Step $step/$total_steps] Voice" \
            --checklist "Enable voice (Whisper speech-to-text + Kokoro text-to-speech)? Needs a one-time admin-panel setting in Open WebUI after first start." \
            12 76 1 \
            "voice" "Whisper + Kokoro - voice input/output for Open WebUI" "$voice_default" \
            3>&1 1>&2 2>&3 | grep -q "voice"; then
            VOICE_FLAG="--voice"
        fi
    else
        [ "$voice_default" = "ON" ] && VOICE_FLAG="--voice"
    fi

    local N8N_FLAG="--no-n8n"
    local n8n_default="ON"
    if [ -n "$PREVIOUS_TIER" ]; then
        [[ ",$PREVIOUS_ENABLED_OPTIONAL," == *",n8n,"* ]] && n8n_default="ON" || n8n_default="OFF"
    fi
    step=$((step + 1))
    if [ -z "$TESTING" ]; then
        if whiptail --backtitle "$BACKTITLE" --title "[Step $step/$total_steps] n8n" \
            --checklist "Enable n8n (workflow automation)? A random admin password is generated once and printed after first start." \
            12 76 1 \
            "n8n" "n8n - visual workflow automation" "$n8n_default" \
            3>&1 1>&2 2>&3 | grep -q "n8n"; then
            N8N_FLAG="--n8n"
        fi
    else
        [ "$n8n_default" = "ON" ] && N8N_FLAG="--n8n"
    fi

    # LiteLLM/SearXNG/Vane/LocalAI default OFF, unlike RAG/voice/n8n
    # above - see tiers.py's ServiceDefinition comments for why.
    local LITELLM_FLAG="--no-litellm"
    local litellm_default="OFF"
    if [ -n "$PREVIOUS_TIER" ]; then
        [[ ",$PREVIOUS_ENABLED_OPTIONAL," == *",litellm,"* ]] && litellm_default="ON" || litellm_default="OFF"
    fi
    step=$((step + 1))
    if [ -z "$TESTING" ]; then
        if whiptail --backtitle "$BACKTITLE" --title "[Step $step/$total_steps] LiteLLM" \
            --checklist "Enable LiteLLM (universal LLM proxy for local + cloud providers)? Ships a starter config with one working Ollama model." \
            12 76 1 \
            "litellm" "LiteLLM - one endpoint for local + cloud LLM providers" "$litellm_default" \
            3>&1 1>&2 2>&3 | grep -q "litellm"; then
            LITELLM_FLAG="--litellm"
        fi
    else
        [ "$litellm_default" = "ON" ] && LITELLM_FLAG="--litellm"
    fi

    local SEARXNG_FLAG="--no-searxng"
    local searxng_default="OFF"
    if [ -n "$PREVIOUS_TIER" ]; then
        [[ ",$PREVIOUS_ENABLED_OPTIONAL," == *",searxng,"* ]] && searxng_default="ON" || searxng_default="OFF"
    fi
    step=$((step + 1))
    if [ -z "$TESTING" ]; then
        if whiptail --backtitle "$BACKTITLE" --title "[Step $step/$total_steps] SearXNG" \
            --checklist "Enable SearXNG (self-hosted metasearch engine)?" \
            12 76 1 \
            "searxng" "SearXNG - private metasearch" "$searxng_default" \
            3>&1 1>&2 2>&3 | grep -q "searxng"; then
            SEARXNG_FLAG="--searxng"
        fi
    else
        [ "$searxng_default" = "ON" ] && SEARXNG_FLAG="--searxng"
    fi

    local VANE_FLAG="--no-vane"
    local vane_default="OFF"
    if [ -n "$PREVIOUS_TIER" ]; then
        [[ ",$PREVIOUS_ENABLED_OPTIONAL," == *",vane,"* ]] && vane_default="ON" || vane_default="OFF"
    fi
    step=$((step + 1))
    if [ -z "$TESTING" ]; then
        if whiptail --backtitle "$BACKTITLE" --title "[Step $step/$total_steps] Vane" \
            --checklist "Enable Vane, formerly Perplexica (AI-powered search)? Needs SearXNG - enabled automatically alongside it if not also checked." \
            12 76 1 \
            "vane" "Vane - AI search with cited sources" "$vane_default" \
            3>&1 1>&2 2>&3 | grep -q "vane"; then
            VANE_FLAG="--vane"
        fi
    else
        [ "$vane_default" = "ON" ] && VANE_FLAG="--vane"
    fi
    # Hard dependency, not just a suggestion - see write_stack()'s own
    # auto-enable too, this just keeps the printed summary honest.
    [ "$VANE_FLAG" = "--vane" ] && SEARXNG_FLAG="--searxng"

    local LOCALAI_FLAG="--no-localai"
    local localai_default="OFF"
    if [ -n "$PREVIOUS_TIER" ]; then
        [[ ",$PREVIOUS_ENABLED_OPTIONAL," == *",localai,"* ]] && localai_default="ON" || localai_default="OFF"
    fi
    step=$((step + 1))
    if [ -z "$TESTING" ]; then
        if whiptail --backtitle "$BACKTITLE" --title "[Step $step/$total_steps] LocalAI" \
            --checklist "Enable LocalAI (OpenAI-compatible multi-modal inference server)?" \
            12 76 1 \
            "localai" "LocalAI - broader model format support than Ollama" "$localai_default" \
            3>&1 1>&2 2>&3 | grep -q "localai"; then
            LOCALAI_FLAG="--localai"
        fi
    else
        [ "$localai_default" = "ON" ] && LOCALAI_FLAG="--localai"
    fi

    # Only asked when detect_shell() actually found a co-located Vulcan
    # stack (VULCAN_STACK_FOUND/VULCAN_STACK_PATH, sourced above via
    # eval) - no detection logic duplicated here, same as every other
    # step in this file. Silent (no step at all) when nothing is found,
    # matching the standalone-by-default requirement.
    local INTEGRATE_VULCAN_FLAG="--no-integrate-vulcan"
    if [ "${VULCAN_STACK_FOUND:-false}" = "true" ]; then

        step=$((step + 1))
        if [ -z "$TESTING" ]; then
            if whiptail --backtitle "$BACKTITLE" --title "[Step $step/$total_steps] Vulcan Integration" \
                --yesno "Found a Vulcan stack at ${VULCAN_STACK_PATH:-} - cross-check ports and add a Homepage section for Anvil's enabled services?" \
                10 76; then
                INTEGRATE_VULCAN_FLAG="--integrate-vulcan"
            fi
        else
            INTEGRATE_VULCAN_FLAG="--integrate-vulcan"
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
    log_info "RAG: $RAG_FLAG"
    log_info "Voice: $VOICE_FLAG"
    log_info "n8n: $N8N_FLAG"
    log_info "LiteLLM: $LITELLM_FLAG"
    log_info "SearXNG: $SEARXNG_FLAG"
    log_info "Vane: $VANE_FLAG"
    log_info "LocalAI: $LOCALAI_FLAG"
    log_info "Vulcan integration: $INTEGRATE_VULCAN_FLAG"
    log_info "PUID=$PUID PGID=$PGID"
    log_info "Start: $START_FLAG"

    # Show a full settings summary before executing (Security Onion pattern).
    if [ -z "$TESTING" ]; then
        local summary=""
        summary+="Tier:       $TIER\n"
        summary+="GPU:        $gpu_desc (${vram_gb}GB)\n"
        summary+="PUID/PGID:  $PUID / $PGID\n"
        summary+="ComfyUI:    $([ "$COMFYUI_FLAG" = "--comfyui" ] && echo "yes" || echo "no")\n"
        summary+="InvokeAI:   $([ "$INVOKEAI_FLAG" = "--invokeai" ] && echo "yes" || echo "no")\n"
        summary+="RAG:        $([ "$RAG_FLAG" = "--rag" ] && echo "yes" || echo "no")\n"
        summary+="Voice:      $([ "$VOICE_FLAG" = "--voice" ] && echo "yes" || echo "no")\n"
        summary+="n8n:        $([ "$N8N_FLAG" = "--n8n" ] && echo "yes" || echo "no")\n"
        summary+="LiteLLM:    $([ "$LITELLM_FLAG" = "--litellm" ] && echo "yes" || echo "no")\n"
        summary+="SearXNG:    $([ "$SEARXNG_FLAG" = "--searxng" ] && echo "yes" || echo "no")\n"
        summary+="Vane:       $([ "$VANE_FLAG" = "--vane" ] && echo "yes" || echo "no")\n"
        summary+="LocalAI:    $([ "$LOCALAI_FLAG" = "--localai" ] && echo "yes" || echo "no")\n"
        if [ "${VULCAN_STACK_FOUND:-false}" = "true" ]; then
            summary+="Vulcan:     $([ "$INTEGRATE_VULCAN_FLAG" = "--integrate-vulcan" ] && echo "yes" || echo "no")\n"
        fi
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
            $COMFYUI_FLAG $INVOKEAI_FLAG $RAG_FLAG $VOICE_FLAG $N8N_FLAG \
            $LITELLM_FLAG $SEARXNG_FLAG $VANE_FLAG $LOCALAI_FLAG $INTEGRATE_VULCAN_FLAG \
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
        "This will start the stack using $compose_file, reassigning any port already in use." \
        "$ANVIL_BIN" start
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
    if grep -q "qdrant" "$compose_file" 2>/dev/null; then
        status_text+="Qdrant:     http://localhost:6333/dashboard\n"
    fi
    if grep -q "  whisper:" "$compose_file" 2>/dev/null; then
        status_text+="Whisper:    http://localhost:9000\n"
    fi
    if grep -q "  tts:" "$compose_file" 2>/dev/null; then
        status_text+="Kokoro TTS: http://localhost:8880\n"
    fi
    if grep -q "  n8n:" "$compose_file" 2>/dev/null; then
        status_text+="n8n:        http://localhost:5678\n"
    fi
    if grep -q "dashboard" "$compose_file" 2>/dev/null; then
        status_text+="Dashboard:  http://localhost:8080\n"
    fi

    whiptail --backtitle "$BACKTITLE" --title "View Status" \
        --msgbox "$status_text" 16 70
}

# --- Uninstall ---------------------------------------------------------

uninstall_flow() {

    local purge_flags=()

    if whiptail --backtitle "$BACKTITLE" --title "Uninstall Stack" \
        --yesno "Also delete stack/data/ - real downloaded models, tens to hundreds of GB? (default: No - keep them)" 10 70 --defaultno; then
        purge_flags=(--purge-data)
    fi

    confirm_and_run "Uninstall Stack" \
        "This will stop the running stack (if any) and delete stack/docker-compose.yml, its state file, and stack/dashboard/. Downloaded models are always kept unless you said yes above." \
        "$ANVIL_BIN" uninstall --non-interactive --yes "${purge_flags[@]}"
}

# --- Entry point -----------------------------------------------------

if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then

    # type -P, not command -v: this script defines its own `whiptail`
    # shell function above (the --fullbuttons wrapper), and `command -v`
    # reports functions as a match too - it would always "find" whiptail
    # here even with the real binary missing. -P forces a real PATH
    # search, ignoring functions/aliases/builtins.
    if ! type -P whiptail >/dev/null 2>&1; then

        echo "whiptail not found - installing it (needed for this menu)..."
        SUDO=""
        [ "$EUID" -ne 0 ] && SUDO="sudo"

        if command -v apt-get >/dev/null 2>&1; then
            $SUDO apt-get update -qq && $SUDO apt-get install -y whiptail
        elif command -v dnf >/dev/null 2>&1; then
            $SUDO dnf install -y newt
        elif command -v pacman >/dev/null 2>&1; then
            $SUDO pacman -Sy --noconfirm libnewt
        elif command -v zypper >/dev/null 2>&1; then
            $SUDO zypper install -y newt
        elif command -v apk >/dev/null 2>&1; then
            $SUDO apk add --no-cache newt
        fi

        if ! type -P whiptail >/dev/null 2>&1; then
            echo "whiptail is required but could not be auto-installed. Install it manually (Debian/Ubuntu: whiptail, Fedora/RHEL: newt, Arch: libnewt, openSUSE: newt) and try again." >&2
            exit 1
        fi
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
