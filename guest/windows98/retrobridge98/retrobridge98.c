#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winsock.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include "rbproto.h"
#include "resource.h"

#define VIEW_WIDTH 640
#define VIEW_HEIGHT 480
#define FRAME_BYTES (VIEW_WIDTH * VIEW_HEIGHT * 2UL)
#define COMPRESSED_BYTES (FRAME_BYTES + (FRAME_BYTES / 255UL) + 16UL)
#define WM_RB_FRAME (WM_APP + 1)
#define WM_RB_STATUS (WM_APP + 2)
#define WM_RB_DISCONNECTED (WM_APP + 3)
#define WM_RB_DIALOG (WM_APP + 4)
#define WM_RB_HISTORY (WM_APP + 5)
#define ID_BACK 101
#define ID_FORWARD 102
#define ID_RELOAD 103
#define ID_STOP 104
#define ID_ADDRESS 105
#define ID_GO 106
#define ID_VIEW 107
#define ID_STATUS 108
#define ID_FILE_DOWNLOADS 201
#define ID_FILE_EXIT 202
#define ID_EDIT_COPY 210
#define ID_EDIT_CUT 211
#define ID_EDIT_PASTE 212
#define ID_EDIT_FIND 213
#define ID_EDIT_SELECT_ALL 214
#define ID_VIEW_HOME 220
#define ID_VIEW_RELOAD 221
#define ID_VIEW_STOP 222
#define ID_GO_ADDRESS 229
#define ID_GO_BACK 230
#define ID_GO_FORWARD 231
#define ID_FAVORITE_ADD 240
#define ID_FAVORITE_MANAGE 241
#define ID_FAVORITE_FIRST 250
#define ID_FAVORITE_LAST 269
#define ID_HELP_DIAGNOSTICS 280
#define ID_HELP_ABOUT 281
#define ID_FIND_EDIT 301
#define ID_FIND_NEXT 302
#define ID_FIND_PREVIOUS 303
#define OUTGOING_COUNT 32
#define OUTGOING_BYTES 65536UL
#define MAX_FAVORITES 20
#define MAX_DOWNLOAD_HISTORY 50

typedef struct favorite_entry {
    char title[129];
    char url[1025];
} favorite_entry;

typedef struct download_record {
    unsigned char status;
    unsigned long timestamp;
    unsigned long size;
    char name[181];
} download_record;

typedef struct text_prompt_context {
    const char *caption;
    const char *message;
    const char *initial;
    char *result;
    int result_size;
} text_prompt_context;

typedef struct outgoing_message {
    unsigned short type;
    unsigned long length;
    unsigned char payload[OUTGOING_BYTES];
} outgoing_message;

static HINSTANCE g_instance;
static HWND g_main;
static HWND g_view;
static HWND g_address;
static HWND g_status;
static HWND g_find_window;
static HWND g_find_edit;
static WNDPROC g_old_edit_proc;
static WNDPROC g_old_find_edit_proc;
static SOCKET g_socket = INVALID_SOCKET;
static HANDLE g_thread;
static volatile BOOL g_quit = FALSE;
static CRITICAL_SECTION g_frame_lock;
static CRITICAL_SECTION g_socket_lock;
static CRITICAL_SECTION g_queue_lock;
static CRITICAL_SECTION g_status_lock;
static CRITICAL_SECTION g_dialog_lock;
static CRITICAL_SECTION g_history_lock;
static unsigned char *g_front;
static unsigned char *g_back;
static unsigned char *g_compressed;
static BOOL g_have_frame = FALSE;
static char g_status_text[256] = "Starting...";
static char g_page_title[128] = "RetroBridge98";
static char g_current_url[1024] = "";
static char g_server[64] = "10.0.2.2";
static int g_port = 9866;
static char g_token[RB_TOKEN_LENGTH + 1];
static outgoing_message g_outgoing[OUTGOING_COUNT];
static int g_outgoing_head = 0;
static int g_outgoing_tail = 0;
static int g_outgoing_size = 0;
static outgoing_message g_mouse_move;
static BOOL g_have_mouse_move = FALSE;
static unsigned long g_capabilities = 0;
static BOOL g_authenticated = FALSE;
static BOOL g_authentication_failed = FALSE;
static char g_favorites_path[MAX_PATH];
static HMENU g_favorites_menu;
static favorite_entry g_favorites[MAX_FAVORITES];
static int g_favorite_count = 0;
static download_record g_downloads[MAX_DOWNLOAD_HISTORY];
static int g_download_count = 0;
static HWND g_download_dialog = NULL;
static HANDLE g_dialog_event = NULL;
static unsigned long g_dialog_id = 0;
static unsigned char g_dialog_kind = 0;
static char g_dialog_message[2049];
static char g_dialog_default[1025];
static char g_dialog_response[1025];
static BOOL g_dialog_accepted = FALSE;
static unsigned short g_host_version[3] = {0, 0, 0};
static BOOL g_have_host_version = FALSE;

static LRESULT CALLBACK find_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam);
static LRESULT CALLBACK find_edit_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam);
static BOOL CALLBACK text_prompt_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam);
static BOOL CALLBACK favorites_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam);
static BOOL CALLBACK downloads_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam);

static void set_status(const char *text)
{
    EnterCriticalSection(&g_status_lock);
    lstrcpyn(g_status_text, text, sizeof(g_status_text));
    LeaveCriticalSection(&g_status_lock);
    PostMessage(g_main, WM_RB_STATUS, 0, 0);
}

static unsigned char modifiers(void)
{
    unsigned char value = 0;
    if (GetKeyState(VK_SHIFT) & 0x8000) value |= 1;
    if (GetKeyState(VK_CONTROL) & 0x8000) value |= 2;
    if (GetKeyState(VK_MENU) & 0x8000) value |= 4;
    return value;
}

static int queue_message(unsigned short type, const void *payload, unsigned long length)
{
    outgoing_message *message;
    int result = 0;
    int is_mouse_move = type == RB_MSG_POINTER && length >= 5 &&
                        ((const unsigned char *)payload)[4] == 1;
    if (length > OUTGOING_BYTES) return 0;
    EnterCriticalSection(&g_socket_lock);
    if (g_socket != INVALID_SOCKET) result = 1;
    LeaveCriticalSection(&g_socket_lock);
    if (!result) return 0;
    EnterCriticalSection(&g_queue_lock);
    if (is_mouse_move) {
        g_mouse_move.type = type;
        g_mouse_move.length = length;
        memcpy(g_mouse_move.payload, payload, length);
        g_have_mouse_move = TRUE;
    } else if (g_outgoing_size < OUTGOING_COUNT) {
        message = &g_outgoing[g_outgoing_tail];
        message->type = type;
        message->length = length;
        if (length > 0) memcpy(message->payload, payload, length);
        g_outgoing_tail = (g_outgoing_tail + 1) % OUTGOING_COUNT;
        g_outgoing_size++;
    } else {
        result = 0;
    }
    LeaveCriticalSection(&g_queue_lock);
    if (!result) set_status("Input queue full; waiting for renderer...");
    return result;
}

static int flush_outgoing(SOCKET sock)
{
    outgoing_message message;
    int have_message;
    do {
        have_message = 0;
        EnterCriticalSection(&g_queue_lock);
        if (g_outgoing_size > 0) {
            message = g_outgoing[g_outgoing_head];
            g_outgoing_head = (g_outgoing_head + 1) % OUTGOING_COUNT;
            g_outgoing_size--;
            have_message = 1;
        }
        LeaveCriticalSection(&g_queue_lock);
        if (have_message && !rb_send_packet(sock, message.type, message.payload, message.length)) return 0;
    } while (have_message);
    EnterCriticalSection(&g_queue_lock);
    if (g_have_mouse_move) {
        message = g_mouse_move;
        g_have_mouse_move = FALSE;
        have_message = 1;
    } else {
        have_message = 0;
    }
    LeaveCriticalSection(&g_queue_lock);
    if (have_message && !rb_send_packet(sock, message.type, message.payload, message.length)) return 0;
    return 1;
}

static void clear_outgoing(void)
{
    EnterCriticalSection(&g_queue_lock);
    g_outgoing_head = 0;
    g_outgoing_tail = 0;
    g_outgoing_size = 0;
    g_have_mouse_move = FALSE;
    LeaveCriticalSection(&g_queue_lock);
}

static void send_control(unsigned char action)
{
    queue_message(RB_MSG_CONTROL, &action, 1);
}

static void focus_address(void)
{
    SetFocus(g_address);
    SendMessage(g_address, EM_SETSEL, 0, -1);
}

static void send_navigation(void)
{
    char address[1024];
    GetWindowText(g_address, address, sizeof(address));
    if (address[0] != 0) queue_message(RB_MSG_NAVIGATE, address, (unsigned long)strlen(address));
    SetFocus(g_view);
}

static void send_pointer(unsigned short x, unsigned short y, unsigned char action,
                         unsigned char button, short wheel)
{
    unsigned char payload[8];
    rb_put_u16(payload, x);
    rb_put_u16(payload + 2, y);
    payload[4] = action;
    payload[5] = button;
    rb_put_u16(payload + 6, (unsigned short)wheel);
    queue_message(RB_MSG_POINTER, payload, sizeof(payload));
}

static void send_key(unsigned short vkey, unsigned char action, unsigned char character)
{
    unsigned char payload[5];
    rb_put_u16(payload, vkey);
    payload[2] = action;
    payload[3] = modifiers();
    payload[4] = character;
    queue_message(RB_MSG_KEY, payload, sizeof(payload));
}

static void send_clipboard_request(unsigned char action)
{
    queue_message(RB_MSG_CLIPBOARD, &action, 1);
}

static void paste_guest_clipboard(void)
{
    HANDLE data;
    const char *text;
    unsigned long length;
    unsigned char *payload;
    if (!(g_capabilities & RB_CAP_CLIPBOARD)) {
        set_status("The host renderer does not support clipboard bridging.");
        return;
    }
    if (!OpenClipboard(g_main)) return;
    data = GetClipboardData(CF_TEXT);
    if (data == NULL) {
        CloseClipboard();
        return;
    }
    text = (const char *)GlobalLock(data);
    if (text == NULL) {
        CloseClipboard();
        return;
    }
    length = (unsigned long)strlen(text);
    if (length > OUTGOING_BYTES - 1) length = OUTGOING_BYTES - 1;
    payload = (unsigned char *)GlobalAlloc(GMEM_FIXED, length + 1);
    if (payload != NULL) {
        payload[0] = RB_CLIPBOARD_PASTE;
        memcpy(payload + 1, text, length);
        queue_message(RB_MSG_CLIPBOARD, payload, length + 1);
        GlobalFree(payload);
    }
    GlobalUnlock(data);
    CloseClipboard();
}

static void set_guest_clipboard(const char *text, unsigned long length)
{
    HGLOBAL data;
    char *target;
    if (!OpenClipboard(g_main)) return;
    EmptyClipboard();
    data = GlobalAlloc(GMEM_MOVEABLE, length + 1);
    if (data != NULL) {
        target = (char *)GlobalLock(data);
        if (target != NULL) {
            memcpy(target, text, length);
            target[length] = 0;
            GlobalUnlock(data);
            if (SetClipboardData(CF_TEXT, data) == NULL) GlobalFree(data);
        } else {
            GlobalFree(data);
        }
    }
    CloseClipboard();
}

static void send_find(BOOL backwards)
{
    char text[256];
    unsigned char payload[257];
    int length;
    if (g_find_edit == NULL) return;
    length = GetWindowText(g_find_edit, text, sizeof(text));
    if (length <= 0) return;
    payload[0] = backwards ? 1 : 0;
    memcpy(payload + 1, text, length);
    queue_message(RB_MSG_FIND, payload, (unsigned long)length + 1);
}

static void show_find_window(void)
{
    if (g_find_window == NULL) {
        g_find_window = CreateWindowEx(WS_EX_DLGMODALFRAME, "RetroBridgeFind", "Find",
                         WS_POPUP | WS_CAPTION | WS_SYSMENU,
                         CW_USEDEFAULT, CW_USEDEFAULT, 330, 105,
                         g_main, NULL, GetModuleHandle(NULL), NULL);
        g_find_edit = CreateWindowEx(WS_EX_CLIENTEDGE, "EDIT", "",
                      WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL,
                      10, 12, 190, 22, g_find_window, (HMENU)ID_FIND_EDIT, NULL, NULL);
        g_old_find_edit_proc = (WNDPROC)SetWindowLong(
            g_find_edit, GWL_WNDPROC, (LONG)find_edit_proc);
        CreateWindow("BUTTON", "Next", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_DEFPUSHBUTTON,
                     205, 11, 50, 24, g_find_window, (HMENU)ID_FIND_NEXT, NULL, NULL);
        CreateWindow("BUTTON", "Previous", WS_CHILD | WS_VISIBLE | WS_TABSTOP,
                     258, 11, 60, 24, g_find_window, (HMENU)ID_FIND_PREVIOUS, NULL, NULL);
    }
    ShowWindow(g_find_window, SW_SHOW);
    SetForegroundWindow(g_find_window);
    SetFocus(g_find_edit);
}

static void sanitize_favorite_title(char *text)
{
    char *cursor = text;
    while (*cursor != 0) {
        if (*cursor == '|' || (unsigned char)*cursor < 32) *cursor = ' ';
        cursor++;
    }
    while (*text == ' ') memmove(text, text + 1, strlen(text));
    if (text[0] == 0) lstrcpy(text, "Favorite");
}

static void load_favorites(void)
{
    int index;
    char key[24];
    char value[1200];
    char *separator;
    g_favorite_count = 0;
    for (index = 0; index < MAX_FAVORITES; index++) {
        wsprintf(key, "Favorite%d", index + 1);
        GetPrivateProfileString("Favorites", key, "", value, sizeof(value), g_favorites_path);
        if (value[0] == 0) break;
        separator = strchr(value, '|');
        if (separator == NULL || separator[1] == 0) continue;
        *separator = 0;
        lstrcpyn(g_favorites[g_favorite_count].title, value,
                 sizeof(g_favorites[g_favorite_count].title));
        lstrcpyn(g_favorites[g_favorite_count].url, separator + 1,
                 sizeof(g_favorites[g_favorite_count].url));
        sanitize_favorite_title(g_favorites[g_favorite_count].title);
        g_favorite_count++;
    }
}

static void save_favorites(void)
{
    int index;
    char key[24];
    char value[1200];
    for (index = 0; index < g_favorite_count; index++) {
        wsprintf(key, "Favorite%d", index + 1);
        wsprintf(value, "%s|%s", g_favorites[index].title, g_favorites[index].url);
        WritePrivateProfileString("Favorites", key, value, g_favorites_path);
    }
    for (; index < MAX_FAVORITES; index++) {
        wsprintf(key, "Favorite%d", index + 1);
        WritePrivateProfileString("Favorites", key, NULL, g_favorites_path);
    }
    WritePrivateProfileString(NULL, NULL, NULL, g_favorites_path);
}

static void send_favorites_state(void)
{
    unsigned char *payload;
    unsigned long offset = 1;
    unsigned short title_length;
    unsigned short url_length;
    int index;
    if (!(g_capabilities & RB_CAP_FAVORITES_SYNC) || !g_authenticated) return;
    payload = (unsigned char *)GlobalAlloc(GMEM_FIXED, OUTGOING_BYTES);
    if (payload == NULL) return;
    payload[0] = (unsigned char)g_favorite_count;
    for (index = 0; index < g_favorite_count; index++) {
        title_length = (unsigned short)strlen(g_favorites[index].title);
        url_length = (unsigned short)strlen(g_favorites[index].url);
        if (offset + 4UL + title_length + url_length > OUTGOING_BYTES) break;
        rb_put_u16(payload + offset, title_length);
        rb_put_u16(payload + offset + 2, url_length);
        offset += 4;
        memcpy(payload + offset, g_favorites[index].title, title_length);
        offset += title_length;
        memcpy(payload + offset, g_favorites[index].url, url_length);
        offset += url_length;
    }
    payload[0] = (unsigned char)index;
    queue_message(RB_MSG_FAVORITES_STATE, payload, offset);
    GlobalFree(payload);
}

static void rebuild_favorites_menu(void)
{
    int index;
    if (g_favorites_menu == NULL) return;
    for (index = ID_FAVORITE_FIRST; index <= ID_FAVORITE_LAST; index++)
        DeleteMenu(g_favorites_menu, index, MF_BYCOMMAND);
    for (index = 0; index < g_favorite_count; index++)
        AppendMenu(g_favorites_menu, MF_STRING, ID_FAVORITE_FIRST + index,
                   g_favorites[index].title);
    DrawMenuBar(g_main);
}

static void favorites_changed(void)
{
    save_favorites();
    rebuild_favorites_menu();
    send_favorites_state();
}

static void add_current_favorite(void)
{
    int index;
    const char *title;
    if (g_current_url[0] == 0) {
        set_status("Navigate to a page before adding a Favorite.");
        return;
    }
    title = g_page_title[0] != 0 ? g_page_title : "Favorite";
    for (index = 0; index < g_favorite_count; index++) {
        if (lstrcmpi(g_favorites[index].url, g_current_url) == 0) {
            lstrcpyn(g_favorites[index].title, title, sizeof(g_favorites[index].title));
            sanitize_favorite_title(g_favorites[index].title);
            favorites_changed();
            set_status("Existing Favorite updated.");
            return;
        }
    }
    if (g_favorite_count >= MAX_FAVORITES) {
        set_status("Favorites is full (20 entries).");
        return;
    }
    lstrcpyn(g_favorites[g_favorite_count].title, title,
             sizeof(g_favorites[g_favorite_count].title));
    lstrcpyn(g_favorites[g_favorite_count].url, g_current_url,
             sizeof(g_favorites[g_favorite_count].url));
    sanitize_favorite_title(g_favorites[g_favorite_count].title);
    g_favorite_count++;
    favorites_changed();
    set_status("Favorite added.");
}

static void open_favorite(int command)
{
    int index = command - ID_FAVORITE_FIRST;
    if (index < 0 || index >= g_favorite_count) return;
    SetWindowText(g_address, g_favorites[index].url);
    send_navigation();
}

static BOOL CALLBACK text_prompt_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    text_prompt_context *context;
    if (message == WM_INITDIALOG) {
        context = (text_prompt_context *)lparam;
        SetWindowLong(window, DWL_USER, (LONG)context);
        SetWindowText(window, context->caption);
        SetDlgItemText(window, IDC_PROMPT_MESSAGE, context->message);
        SetDlgItemText(window, IDC_PROMPT_EDIT, context->initial);
        SendDlgItemMessage(window, IDC_PROMPT_EDIT, EM_LIMITTEXT,
                           (WPARAM)(context->result_size - 1), 0);
        SendDlgItemMessage(window, IDC_PROMPT_EDIT, EM_SETSEL, 0, -1);
        return TRUE;
    }
    context = (text_prompt_context *)GetWindowLong(window, DWL_USER);
    if (message == WM_COMMAND && LOWORD(wparam) == IDOK) {
        GetDlgItemText(window, IDC_PROMPT_EDIT, context->result, context->result_size);
        EndDialog(window, IDOK);
        return TRUE;
    }
    if (message == WM_COMMAND && LOWORD(wparam) == IDCANCEL) {
        EndDialog(window, IDCANCEL);
        return TRUE;
    }
    return FALSE;
}

static int show_text_prompt(const char *caption, const char *message, const char *initial,
                            char *result, int result_size)
{
    text_prompt_context context;
    context.caption = caption;
    context.message = message;
    context.initial = initial;
    context.result = result;
    context.result_size = result_size;
    result[0] = 0;
    return DialogBoxParam(g_instance, MAKEINTRESOURCE(IDD_TEXT_PROMPT), g_main,
                          text_prompt_proc, (LPARAM)&context) == IDOK;
}

static void populate_favorites_dialog(HWND window, int selection)
{
    int index;
    HWND list = GetDlgItem(window, IDC_FAVORITES_LIST);
    SendMessage(list, LB_RESETCONTENT, 0, 0);
    for (index = 0; index < g_favorite_count; index++)
        SendMessage(list, LB_ADDSTRING, 0, (LPARAM)g_favorites[index].title);
    if (g_favorite_count > 0) {
        if (selection < 0) selection = 0;
        if (selection >= g_favorite_count) selection = g_favorite_count - 1;
        SendMessage(list, LB_SETCURSEL, selection, 0);
    }
}

static BOOL CALLBACK favorites_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    int selection;
    char renamed[129];
    favorite_entry temporary;
    (void)lparam;
    if (message == WM_INITDIALOG) {
        populate_favorites_dialog(window, 0);
        return TRUE;
    }
    if (message != WM_COMMAND) return FALSE;
    selection = (int)SendDlgItemMessage(window, IDC_FAVORITES_LIST, LB_GETCURSEL, 0, 0);
    if (LOWORD(wparam) == IDCANCEL) {
        EndDialog(window, IDCANCEL);
        return TRUE;
    }
    if ((LOWORD(wparam) == IDC_FAVORITE_OPEN ||
         (LOWORD(wparam) == IDC_FAVORITES_LIST && HIWORD(wparam) == LBN_DBLCLK)) &&
        selection >= 0 && selection < g_favorite_count) {
        SetWindowText(g_address, g_favorites[selection].url);
        send_navigation();
        EndDialog(window, IDOK);
        return TRUE;
    }
    if (LOWORD(wparam) == IDC_FAVORITE_RENAME && selection >= 0 &&
        selection < g_favorite_count) {
        if (show_text_prompt("Rename Favorite", "Enter a new Favorite name:",
                             g_favorites[selection].title, renamed, sizeof(renamed))) {
            sanitize_favorite_title(renamed);
            lstrcpyn(g_favorites[selection].title, renamed,
                     sizeof(g_favorites[selection].title));
            favorites_changed();
            populate_favorites_dialog(window, selection);
        }
        return TRUE;
    }
    if (LOWORD(wparam) == IDC_FAVORITE_DELETE && selection >= 0 &&
        selection < g_favorite_count) {
        if (MessageBox(window, "Delete the selected Favorite?", "Manage Favorites",
                       MB_YESNO | MB_ICONQUESTION) == IDYES) {
            memmove(&g_favorites[selection], &g_favorites[selection + 1],
                    (g_favorite_count - selection - 1) * sizeof(favorite_entry));
            g_favorite_count--;
            favorites_changed();
            populate_favorites_dialog(window, selection);
        }
        return TRUE;
    }
    if (LOWORD(wparam) == IDC_FAVORITE_UP && selection > 0 && selection < g_favorite_count) {
        temporary = g_favorites[selection - 1];
        g_favorites[selection - 1] = g_favorites[selection];
        g_favorites[selection] = temporary;
        favorites_changed();
        populate_favorites_dialog(window, selection - 1);
        return TRUE;
    }
    if (LOWORD(wparam) == IDC_FAVORITE_DOWN && selection >= 0 &&
        selection + 1 < g_favorite_count) {
        temporary = g_favorites[selection + 1];
        g_favorites[selection + 1] = g_favorites[selection];
        g_favorites[selection] = temporary;
        favorites_changed();
        populate_favorites_dialog(window, selection + 1);
        return TRUE;
    }
    return FALSE;
}

static int discard_bytes(SOCKET sock, unsigned long length)
{
    unsigned char buffer[512];
    unsigned long amount;
    while (length > 0) {
        amount = length > sizeof(buffer) ? sizeof(buffer) : length;
        if (!rb_recv_all(sock, buffer, amount)) return 0;
        length -= amount;
    }
    return 1;
}

static int decompress_lz4(const unsigned char *source, unsigned long source_length,
                          unsigned char *target, unsigned long target_length)
{
    const unsigned char *input = source;
    const unsigned char *input_end = source + source_length;
    unsigned char *output = target;
    unsigned char *output_end = target + target_length;
    unsigned long literal_length;
    unsigned long match_length;
    unsigned long offset;
    unsigned char token;
    unsigned char extension;
    unsigned char *match;
    while (input < input_end) {
        token = *input++;
        literal_length = token >> 4;
        if (literal_length == 15) {
            do {
                if (input >= input_end) return 0;
                extension = *input++;
                literal_length += extension;
            } while (extension == 255);
        }
        if ((unsigned long)(input_end - input) < literal_length ||
            (unsigned long)(output_end - output) < literal_length) return 0;
        memcpy(output, input, literal_length);
        input += literal_length;
        output += literal_length;
        if (input == input_end) break;
        if (input_end - input < 2) return 0;
        offset = (unsigned long)input[0] | ((unsigned long)input[1] << 8);
        input += 2;
        if (offset == 0 || offset > (unsigned long)(output - target)) return 0;
        match_length = (token & 15) + 4UL;
        if ((token & 15) == 15) {
            do {
                if (input >= input_end) return 0;
                extension = *input++;
                match_length += extension;
            } while (extension == 255);
        }
        if ((unsigned long)(output_end - output) < match_length) return 0;
        match = output - offset;
        while (match_length-- > 0) *output++ = *match++;
    }
    return output == output_end;
}

static int receive_frame(SOCKET sock, unsigned long length)
{
    unsigned char prefix[13];
    unsigned long sequence;
    unsigned short width;
    unsigned short height;
    unsigned long stride;
    unsigned char *swap;
    if (length < sizeof(prefix) || !rb_recv_all(sock, prefix, sizeof(prefix))) return 0;
    sequence = rb_get_u32(prefix);
    width = rb_get_u16(prefix + 4);
    height = rb_get_u16(prefix + 6);
    stride = rb_get_u32(prefix + 8);
    length -= sizeof(prefix);
    if (width != VIEW_WIDTH || height != VIEW_HEIGHT || stride != VIEW_WIDTH * 2UL ||
        prefix[12] != RB_PIXEL_RGB565_LZ4 || length == 0 || length > COMPRESSED_BYTES) {
        return discard_bytes(sock, length);
    }
    if (!rb_recv_all(sock, g_compressed, length)) return 0;
    if (!decompress_lz4(g_compressed, length, g_back, FRAME_BYTES)) return 0;
    EnterCriticalSection(&g_frame_lock);
    swap = g_front;
    g_front = g_back;
    g_back = swap;
    g_have_frame = TRUE;
    LeaveCriticalSection(&g_frame_lock);
    PostMessage(g_main, WM_RB_FRAME, (WPARAM)sequence, 0);
    return 1;
}

static int receive_text(SOCKET sock, unsigned short type, unsigned long length)
{
    char text[1200];
    char title[180];
    unsigned char kind = 0;
    unsigned long keep = length;
    if (keep >= sizeof(text)) keep = sizeof(text) - 1;
    if (keep > 0 && !rb_recv_all(sock, text, keep)) return 0;
    text[keep] = 0;
    if (length > keep && !discard_bytes(sock, length - keep)) return 0;
    if (type == RB_MSG_STATUS && keep > 0) {
        kind = (unsigned char)text[0];
        memmove(text, text + 1, keep);
        text[keep - 1] = 0;
        if (kind == 1) {
            lstrcpyn(g_current_url, text, sizeof(g_current_url));
            if (GetFocus() != g_address) SetWindowText(g_address, text);
            return 1;
        }
        if (kind == 2) {
            lstrcpyn(g_page_title, text[0] != 0 ? text : "RetroBridge98", sizeof(g_page_title));
            wsprintf(title, "%s - RetroBridge98", g_page_title);
            SetWindowText(g_main, title);
            return 1;
        }
        if (kind == 3) {
            set_status(text[0] == '1' ? "Loading..." : "Done");
            return 1;
        }
    }
    if (type == RB_MSG_ERROR && strcmp(text, "Authentication failed") == 0)
        g_authentication_failed = TRUE;
    set_status(text);
    return 1;
}

static int receive_clipboard(SOCKET sock, unsigned long length)
{
    unsigned char *payload;
    if (length == 0 || length > OUTGOING_BYTES) return discard_bytes(sock, length);
    payload = (unsigned char *)GlobalAlloc(GMEM_FIXED, length);
    if (payload == NULL) return discard_bytes(sock, length);
    if (!rb_recv_all(sock, payload, length)) {
        GlobalFree(payload);
        return 0;
    }
    if (payload[0] == RB_CLIPBOARD_RESULT) {
        set_guest_clipboard((const char *)payload + 1, length - 1);
        set_status("Copied page text to the Windows clipboard.");
    }
    GlobalFree(payload);
    return 1;
}

static int receive_download(SOCKET sock, unsigned long length)
{
    char payload[512];
    char message[600];
    unsigned long keep = length;
    char *name;
    if (keep >= sizeof(payload)) keep = sizeof(payload) - 1;
    if (keep > 0 && !rb_recv_all(sock, payload, keep)) return 0;
    payload[keep] = 0;
    if (length > keep && !discard_bytes(sock, length - keep)) return 0;
    name = keep > 0 ? payload + strlen(payload) + 1 : NULL;
    if (name != NULL && name < payload + keep && strcmp(payload, "complete") == 0)
        wsprintf(message, "Downloaded to host: %s", name);
    else if (name != NULL && name < payload + keep && strcmp(payload, "oversize") == 0)
        wsprintf(message, "Download was too large: %s", name);
    else if (name != NULL && name < payload + keep && strcmp(payload, "failed") == 0)
        wsprintf(message, "Download failed: %s", name);
    else
        lstrcpyn(message, "Download was blocked or cancelled.", sizeof(message));
    set_status(message);
    if (g_capabilities & RB_CAP_DOWNLOAD_HISTORY)
        queue_message(RB_MSG_DOWNLOAD_HISTORY_REQUEST, NULL, 0);
    return 1;
}

static void send_peer_info(void)
{
    unsigned char payload[10];
    if (!(g_capabilities & RB_CAP_PEER_INFO) || !g_authenticated) return;
    rb_put_u16(payload, 0);
    rb_put_u16(payload + 2, 3);
    rb_put_u16(payload + 4, 0);
    rb_put_u32(payload + 6, 0);
    queue_message(RB_MSG_PEER_INFO, payload, sizeof(payload));
}

static int receive_peer_info(SOCKET sock, unsigned long length)
{
    unsigned char payload[10];
    if (length != sizeof(payload)) return discard_bytes(sock, length);
    if (!rb_recv_all(sock, payload, sizeof(payload))) return 0;
    g_host_version[0] = rb_get_u16(payload);
    g_host_version[1] = rb_get_u16(payload + 2);
    g_host_version[2] = rb_get_u16(payload + 4);
    g_have_host_version = TRUE;
    return 1;
}

static int receive_download_history(SOCKET sock, unsigned long length)
{
    unsigned char *payload;
    unsigned long offset = 1;
    unsigned long end;
    unsigned short name_length;
    int count;
    int index;
    int valid = 1;
    if (length < 1 || length > OUTGOING_BYTES) return discard_bytes(sock, length);
    payload = (unsigned char *)GlobalAlloc(GMEM_FIXED, length);
    if (payload == NULL) return discard_bytes(sock, length);
    if (!rb_recv_all(sock, payload, length)) {
        GlobalFree(payload);
        return 0;
    }
    count = payload[0];
    if (count > MAX_DOWNLOAD_HISTORY) valid = 0;
    EnterCriticalSection(&g_history_lock);
    g_download_count = 0;
    for (index = 0; valid && index < count; index++) {
        if (length - offset < 11) {
            valid = 0;
            break;
        }
        g_downloads[index].status = payload[offset];
        g_downloads[index].timestamp = rb_get_u32(payload + offset + 1);
        g_downloads[index].size = rb_get_u32(payload + offset + 5);
        name_length = rb_get_u16(payload + offset + 9);
        offset += 11;
        end = offset + name_length;
        if (name_length == 0 || name_length > 180 || end > length ||
            g_downloads[index].status < RB_DOWNLOAD_COMPLETE ||
            g_downloads[index].status > RB_DOWNLOAD_BLOCKED) {
            valid = 0;
            break;
        }
        memcpy(g_downloads[index].name, payload + offset, name_length);
        g_downloads[index].name[name_length] = 0;
        offset = end;
        g_download_count++;
    }
    if (offset != length) valid = 0;
    if (!valid) g_download_count = 0;
    LeaveCriticalSection(&g_history_lock);
    GlobalFree(payload);
    if (valid && g_download_dialog != NULL)
        PostMessage(g_download_dialog, WM_RB_HISTORY, 0, 0);
    if (!valid) set_status("Renderer sent invalid download history.");
    return 1;
}

static int receive_dialog(SOCKET sock, unsigned long length)
{
    unsigned char *payload;
    unsigned char response[1030];
    char *message;
    char *message_end;
    char *default_value;
    unsigned long response_length = 5;
    if (length < 6 || length > 4096) return discard_bytes(sock, length);
    payload = (unsigned char *)GlobalAlloc(GMEM_FIXED, length + 1);
    if (payload == NULL) return discard_bytes(sock, length);
    if (!rb_recv_all(sock, payload, length)) {
        GlobalFree(payload);
        return 0;
    }
    payload[length] = 0;
    message = (char *)payload + 5;
    message_end = (char *)memchr(message, 0, (char *)payload + length - message);
    if (message_end == NULL || payload[4] < 1 || payload[4] > 3) {
        GlobalFree(payload);
        set_status("Renderer sent an invalid page dialog.");
        return 1;
    }
    default_value = message_end + 1;
    if (default_value > (char *)payload + length) default_value = "";
    EnterCriticalSection(&g_dialog_lock);
    g_dialog_id = rb_get_u32(payload);
    g_dialog_kind = payload[4];
    lstrcpyn(g_dialog_message, message, sizeof(g_dialog_message));
    lstrcpyn(g_dialog_default, default_value, sizeof(g_dialog_default));
    g_dialog_response[0] = 0;
    g_dialog_accepted = FALSE;
    ResetEvent(g_dialog_event);
    LeaveCriticalSection(&g_dialog_lock);
    GlobalFree(payload);
    if (!PostMessage(g_main, WM_RB_DIALOG, 0, 0) ||
        WaitForSingleObject(g_dialog_event, INFINITE) != WAIT_OBJECT_0) return 0;
    EnterCriticalSection(&g_dialog_lock);
    rb_put_u32(response, g_dialog_id);
    response[4] = g_dialog_accepted ? 1 : 0;
    if (g_dialog_kind == 3 && g_dialog_accepted && g_dialog_response[0] != 0) {
        response_length += (unsigned long)strlen(g_dialog_response);
        if (response_length > sizeof(response)) response_length = sizeof(response);
        memcpy(response + 5, g_dialog_response, response_length - 5);
    }
    LeaveCriticalSection(&g_dialog_lock);
    return rb_send_packet(sock, RB_MSG_DIALOG_REPLY, response, response_length);
}

static int send_hello(SOCKET sock)
{
    unsigned char payload[37];
    memcpy(payload, g_token, RB_TOKEN_LENGTH);
    rb_put_u16(payload + 32, VIEW_WIDTH);
    rb_put_u16(payload + 34, VIEW_HEIGHT);
    payload[36] = RB_PIXEL_RGB565_LZ4;
    return rb_send_packet(sock, RB_MSG_HELLO, payload, sizeof(payload));
}

static DWORD WINAPI network_thread(LPVOID unused)
{
    struct sockaddr_in address;
    rb_header header;
    SOCKET sock;
    unsigned char welcome[6];
    fd_set readable;
    struct timeval timeout;
    int selected;
    unsigned long last_ping;
    unsigned char ping[4];
    (void)unused;
    while (!g_quit) {
        set_status("Connecting to the host renderer...");
        g_authenticated = FALSE;
        g_capabilities = 0;
        g_have_host_version = FALSE;
        sock = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
        if (sock == INVALID_SOCKET) {
            Sleep(2000);
            continue;
        }
        memset(&address, 0, sizeof(address));
        address.sin_family = AF_INET;
        address.sin_port = htons((unsigned short)g_port);
        address.sin_addr.s_addr = inet_addr(g_server);
        if (address.sin_addr.s_addr == INADDR_NONE ||
            connect(sock, (struct sockaddr *)&address, sizeof(address)) != 0) {
            closesocket(sock);
            set_status("Host renderer unavailable; retrying...");
            Sleep(2000);
            continue;
        }
        if (!send_hello(sock)) {
            closesocket(sock);
            Sleep(2000);
            continue;
        }
        EnterCriticalSection(&g_socket_lock);
        g_socket = sock;
        LeaveCriticalSection(&g_socket_lock);
        set_status("Authenticating...");
        last_ping = GetTickCount();
        while (!g_quit) {
            if (!flush_outgoing(sock)) break;
            if (GetTickCount() - last_ping >= 5000UL) {
                rb_put_u32(ping, GetTickCount());
                if (!rb_send_packet(sock, RB_MSG_PING, ping, sizeof(ping))) break;
                last_ping = GetTickCount();
            }
            FD_ZERO(&readable);
            FD_SET(sock, &readable);
            timeout.tv_sec = 0;
            timeout.tv_usec = 50000;
            selected = select(0, &readable, NULL, NULL, &timeout);
            if (selected == SOCKET_ERROR) break;
            if (selected == 0) continue;
            if (!rb_recv_header(sock, &header)) break;
            if (header.type == RB_MSG_FRAME) {
                if (!receive_frame(sock, header.length)) break;
            } else if (header.type == RB_MSG_WELCOME) {
                if (header.length != sizeof(welcome) || !rb_recv_all(sock, welcome, sizeof(welcome))) break;
                if (rb_get_u16(welcome) != VIEW_WIDTH || rb_get_u16(welcome + 2) != VIEW_HEIGHT ||
                    welcome[4] != RB_PIXEL_RGB565_LZ4) {
                    set_status("Renderer chose an incompatible display format.");
                    break;
                }
                g_authenticated = TRUE;
                set_status("Connected");
            } else if (header.type == RB_MSG_STATUS || header.type == RB_MSG_ERROR) {
                if (!receive_text(sock, header.type, header.length)) break;
            } else if (header.type == RB_MSG_CAPABILITIES) {
                if (header.length != 4 || !rb_recv_all(sock, ping, 4)) break;
                g_capabilities = rb_get_u32(ping);
                send_peer_info();
                send_favorites_state();
            } else if (header.type == RB_MSG_CLIPBOARD) {
                if (!receive_clipboard(sock, header.length)) break;
            } else if (header.type == RB_MSG_DIALOG) {
                if (!receive_dialog(sock, header.length)) break;
            } else if (header.type == RB_MSG_DOWNLOAD) {
                if (!receive_download(sock, header.length)) break;
            } else if (header.type == RB_MSG_PEER_INFO) {
                if (!receive_peer_info(sock, header.length)) break;
            } else if (header.type == RB_MSG_DOWNLOAD_HISTORY) {
                if (!receive_download_history(sock, header.length)) break;
            } else if (header.type == RB_MSG_PONG) {
                if (!discard_bytes(sock, header.length)) break;
            } else if (!discard_bytes(sock, header.length)) {
                break;
            }
        }
        EnterCriticalSection(&g_socket_lock);
        if (g_socket == sock) g_socket = INVALID_SOCKET;
        LeaveCriticalSection(&g_socket_lock);
        clear_outgoing();
        closesocket(sock);
        g_authenticated = FALSE;
        PostMessage(g_main, WM_RB_DISCONNECTED, 0, 0);
        if (g_authentication_failed) {
            set_status("Pairing rejected. Update or reinstall RetroBridge98.");
            break;
        }
        if (!g_quit) {
            set_status("Connection lost; retrying...");
            Sleep(2000);
        }
    }
    return 0;
}

static void load_configuration(void)
{
    char path[MAX_PATH];
    char *slash;
    char port[16];
    GetModuleFileName(NULL, path, sizeof(path));
    slash = strrchr(path, '\\');
    if (slash != NULL) *(slash + 1) = 0;
    lstrcpyn(g_favorites_path, path, sizeof(g_favorites_path));
    lstrcat(g_favorites_path, "FAVORITES.INI");
    lstrcat(path, "RETROBRIDGE.INI");
    GetPrivateProfileString("RetroBridge", "Server", "10.0.2.2", g_server, sizeof(g_server), path);
    GetPrivateProfileString("RetroBridge", "Port", "9866", port, sizeof(port), path);
    GetPrivateProfileString("RetroBridge", "Token", "", g_token, sizeof(g_token), path);
    g_port = atoi(port);
}

static int valid_token(void)
{
    int index;
    if (strlen(g_token) != RB_TOKEN_LENGTH) return 0;
    for (index = 0; index < RB_TOKEN_LENGTH; index++)
        if (!((g_token[index] >= '0' && g_token[index] <= '9') ||
              (g_token[index] >= 'a' && g_token[index] <= 'f'))) return 0;
    return 1;
}

static LRESULT CALLBACK address_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    static BOOL return_sent = FALSE;
    if (message == WM_KEYDOWN && wparam == VK_RETURN) {
        send_navigation();
        return_sent = TRUE;
        return 0;
    }
    if (message == WM_CHAR && wparam == '\r') {
        if (!return_sent) send_navigation();
        return_sent = FALSE;
        return 0;
    }
    if (message == WM_KEYUP && wparam == VK_RETURN) {
        return_sent = FALSE;
        return 0;
    }
    return CallWindowProc(g_old_edit_proc, window, message, wparam, lparam);
}

static LRESULT CALLBACK find_edit_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    static BOOL return_sent = FALSE;
    if (message == WM_KEYDOWN && wparam == VK_RETURN) {
        send_find(FALSE);
        return_sent = TRUE;
        return 0;
    }
    if (message == WM_CHAR && wparam == '\r') {
        if (!return_sent) send_find(FALSE);
        return_sent = FALSE;
        return 0;
    }
    if (message == WM_KEYUP && wparam == VK_RETURN) {
        return_sent = FALSE;
        return 0;
    }
    if (message == WM_KEYDOWN && wparam == VK_ESCAPE) {
        ShowWindow(g_find_window, SW_HIDE);
        return 0;
    }
    return CallWindowProc(g_old_find_edit_proc, window, message, wparam, lparam);
}

static LRESULT CALLBACK find_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    switch (message) {
    case WM_COMMAND:
        if (LOWORD(wparam) == ID_FIND_NEXT) {
            send_find(FALSE);
            return 0;
        }
        if (LOWORD(wparam) == ID_FIND_PREVIOUS) {
            send_find(TRUE);
            return 0;
        }
        break;
    case WM_CLOSE:
        ShowWindow(window, SW_HIDE);
        return 0;
    }
    return DefWindowProc(window, message, wparam, lparam);
}

static const char *download_status_name(unsigned char status)
{
    if (status == RB_DOWNLOAD_COMPLETE) return "Complete";
    if (status == RB_DOWNLOAD_OVERSIZE) return "Too large";
    if (status == RB_DOWNLOAD_FAILED) return "Failed";
    return "Blocked";
}

static void populate_downloads_dialog(HWND window)
{
    HWND list = GetDlgItem(window, IDC_DOWNLOAD_LIST);
    int index;
    char line[512];
    char date[32];
    time_t when;
    struct tm *local;
    SendMessage(list, LB_RESETCONTENT, 0, 0);
    EnterCriticalSection(&g_history_lock);
    if (g_download_count == 0) {
        SendMessage(list, LB_ADDSTRING, 0, (LPARAM)"No downloads recorded yet.");
    }
    for (index = g_download_count - 1; index >= 0; index--) {
        when = (time_t)g_downloads[index].timestamp;
        local = localtime(&when);
        if (local != NULL)
            wsprintf(date, "%04d-%02d-%02d %02d:%02d",
                     local->tm_year + 1900, local->tm_mon + 1, local->tm_mday,
                     local->tm_hour, local->tm_min);
        else
            lstrcpy(date, "Unknown time");
        wsprintf(line, "%s | %s | %lu bytes | %s",
                 date, download_status_name(g_downloads[index].status),
                 g_downloads[index].size, g_downloads[index].name);
        SendMessage(list, LB_ADDSTRING, 0, (LPARAM)line);
    }
    LeaveCriticalSection(&g_history_lock);
}

static BOOL CALLBACK downloads_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    (void)lparam;
    if (message == WM_INITDIALOG) {
        g_download_dialog = window;
        populate_downloads_dialog(window);
        if (g_capabilities & RB_CAP_DOWNLOAD_HISTORY)
            queue_message(RB_MSG_DOWNLOAD_HISTORY_REQUEST, NULL, 0);
        else
            SendDlgItemMessage(window, IDC_DOWNLOAD_LIST, LB_ADDSTRING, 0,
                               (LPARAM)"Legacy renderer: history is unavailable.");
        return TRUE;
    }
    if (message == WM_RB_HISTORY) {
        populate_downloads_dialog(window);
        return TRUE;
    }
    if (message == WM_COMMAND && LOWORD(wparam) == IDC_DOWNLOAD_REFRESH) {
        if (g_capabilities & RB_CAP_DOWNLOAD_HISTORY)
            queue_message(RB_MSG_DOWNLOAD_HISTORY_REQUEST, NULL, 0);
        return TRUE;
    }
    if (message == WM_COMMAND && LOWORD(wparam) == IDCANCEL) {
        EndDialog(window, IDCANCEL);
        return TRUE;
    }
    if (message == WM_DESTROY) g_download_dialog = NULL;
    return FALSE;
}

static HMENU create_main_menu(void)
{
    HMENU bar = CreateMenu();
    HMENU file = CreatePopupMenu();
    HMENU edit = CreatePopupMenu();
    HMENU view = CreatePopupMenu();
    HMENU go = CreatePopupMenu();
    HMENU help = CreatePopupMenu();
    g_favorites_menu = CreatePopupMenu();
    AppendMenu(file, MF_STRING, ID_FILE_DOWNLOADS, "Download History...");
    AppendMenu(file, MF_SEPARATOR, 0, NULL);
    AppendMenu(file, MF_STRING, ID_FILE_EXIT, "E&xit");
    AppendMenu(edit, MF_STRING, ID_EDIT_COPY, "&Copy\tCtrl+C");
    AppendMenu(edit, MF_STRING, ID_EDIT_CUT, "Cu&t\tCtrl+X");
    AppendMenu(edit, MF_STRING, ID_EDIT_PASTE, "&Paste\tCtrl+V");
    AppendMenu(edit, MF_STRING, ID_EDIT_SELECT_ALL, "Select &All\tCtrl+A");
    AppendMenu(edit, MF_SEPARATOR, 0, NULL);
    AppendMenu(edit, MF_STRING, ID_EDIT_FIND, "&Find...\tCtrl+F");
    AppendMenu(view, MF_STRING, ID_VIEW_HOME, "&Home");
    AppendMenu(view, MF_STRING, ID_VIEW_RELOAD, "&Reload\tF5");
    AppendMenu(view, MF_STRING, ID_VIEW_STOP, "&Stop\tEsc");
    AppendMenu(go, MF_STRING, ID_GO_ADDRESS, "&Open Address...\tCtrl+L / F6");
    AppendMenu(go, MF_SEPARATOR, 0, NULL);
    AppendMenu(go, MF_STRING, ID_GO_BACK, "&Back\tAlt+Left");
    AppendMenu(go, MF_STRING, ID_GO_FORWARD, "&Forward\tAlt+Right");
    AppendMenu(g_favorites_menu, MF_STRING, ID_FAVORITE_ADD, "Add Current Page");
    AppendMenu(g_favorites_menu, MF_STRING, ID_FAVORITE_MANAGE, "Manage Favorites...");
    AppendMenu(g_favorites_menu, MF_SEPARATOR, 0, NULL);
    AppendMenu(help, MF_STRING, ID_HELP_DIAGNOSTICS, "Connection Diagnostics");
    AppendMenu(help, MF_STRING, ID_HELP_ABOUT, "About RetroBridge98");
    AppendMenu(bar, MF_POPUP, (UINT_PTR)file, "&File");
    AppendMenu(bar, MF_POPUP, (UINT_PTR)edit, "&Edit");
    AppendMenu(bar, MF_POPUP, (UINT_PTR)view, "&View");
    AppendMenu(bar, MF_POPUP, (UINT_PTR)go, "&Go");
    AppendMenu(bar, MF_POPUP, (UINT_PTR)g_favorites_menu, "F&avorites");
    AppendMenu(bar, MF_POPUP, (UINT_PTR)help, "&Help");
    return bar;
}

static LRESULT CALLBACK view_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    PAINTSTRUCT paint;
    struct {
        BITMAPINFOHEADER header;
        DWORD masks[3];
    } bitmap;
    HDC dc;
    POINT point;
    switch (message) {
    case WM_PAINT:
        dc = BeginPaint(window, &paint);
        EnterCriticalSection(&g_frame_lock);
        if (g_have_frame) {
            memset(&bitmap, 0, sizeof(bitmap));
            bitmap.header.biSize = sizeof(BITMAPINFOHEADER);
            bitmap.header.biWidth = VIEW_WIDTH;
            bitmap.header.biHeight = -VIEW_HEIGHT;
            bitmap.header.biPlanes = 1;
            bitmap.header.biBitCount = 16;
            bitmap.header.biCompression = BI_BITFIELDS;
            bitmap.masks[0] = 0xF800UL;
            bitmap.masks[1] = 0x07E0UL;
            bitmap.masks[2] = 0x001FUL;
            SetDIBitsToDevice(dc, 0, 0, VIEW_WIDTH, VIEW_HEIGHT, 0, 0, 0,
                              VIEW_HEIGHT, g_front, (BITMAPINFO *)&bitmap, DIB_RGB_COLORS);
        } else {
            FillRect(dc, &paint.rcPaint, (HBRUSH)GetStockObject(BLACK_BRUSH));
        }
        LeaveCriticalSection(&g_frame_lock);
        EndPaint(window, &paint);
        return 0;
    case WM_LBUTTONDOWN:
        SetFocus(window);
        SetCapture(window);
        send_pointer((unsigned short)LOWORD(lparam), (unsigned short)HIWORD(lparam), 2, 1, 0);
        return 0;
    case WM_LBUTTONUP:
        ReleaseCapture();
        send_pointer((unsigned short)LOWORD(lparam), (unsigned short)HIWORD(lparam), 3, 1, 0);
        return 0;
    case WM_LBUTTONDBLCLK:
        SetFocus(window);
        send_pointer((unsigned short)LOWORD(lparam), (unsigned short)HIWORD(lparam),
                     2, (unsigned char)(1 | (2 << 4)), 0);
        send_pointer((unsigned short)LOWORD(lparam), (unsigned short)HIWORD(lparam),
                     3, (unsigned char)(1 | (2 << 4)), 0);
        return 0;
    case WM_MBUTTONDOWN:
        SetFocus(window);
        SetCapture(window);
        send_pointer((unsigned short)LOWORD(lparam), (unsigned short)HIWORD(lparam), 2, 3, 0);
        return 0;
    case WM_MBUTTONUP:
        ReleaseCapture();
        send_pointer((unsigned short)LOWORD(lparam), (unsigned short)HIWORD(lparam), 3, 3, 0);
        return 0;
    case WM_RBUTTONDOWN:
        SetFocus(window);
        SetCapture(window);
        send_pointer((unsigned short)LOWORD(lparam), (unsigned short)HIWORD(lparam), 2, 2, 0);
        return 0;
    case WM_RBUTTONUP:
        ReleaseCapture();
        send_pointer((unsigned short)LOWORD(lparam), (unsigned short)HIWORD(lparam), 3, 2, 0);
        return 0;
    case WM_MOUSEMOVE:
        send_pointer((unsigned short)LOWORD(lparam), (unsigned short)HIWORD(lparam), 1,
                     (wparam & MK_LBUTTON) ? 1 : ((wparam & MK_RBUTTON) ? 2 :
                     ((wparam & MK_MBUTTON) ? 3 : 0)), 0);
        return 0;
    case WM_MOUSEWHEEL:
        point.x = (short)LOWORD(lparam);
        point.y = (short)HIWORD(lparam);
        ScreenToClient(window, &point);
        if (point.x < 0) point.x = 0;
        if (point.y < 0) point.y = 0;
        if (point.x >= VIEW_WIDTH) point.x = VIEW_WIDTH - 1;
        if (point.y >= VIEW_HEIGHT) point.y = VIEW_HEIGHT - 1;
        send_pointer((unsigned short)point.x, (unsigned short)point.y, 4, 0,
                     (short)HIWORD(wparam));
        return 0;
    case WM_KEYDOWN:
        if (GetKeyState(VK_CONTROL) & 0x8000) {
            if (wparam == 'L') {
                focus_address();
                return 0;
            }
            if (wparam == 'F') {
                show_find_window();
                return 0;
            }
            if (wparam == 'C') {
                send_clipboard_request(RB_CLIPBOARD_COPY);
                return 0;
            }
            if (wparam == 'X') {
                send_clipboard_request(RB_CLIPBOARD_CUT);
                return 0;
            }
            if (wparam == 'V') {
                paste_guest_clipboard();
                return 0;
            }
        }
        if ((GetKeyState(VK_MENU) & 0x8000) && wparam == VK_LEFT) {
            send_control(1);
            return 0;
        }
        if ((GetKeyState(VK_MENU) & 0x8000) && wparam == VK_RIGHT) {
            send_control(2);
            return 0;
        }
        if (wparam == VK_F5) {
            send_control(3);
            return 0;
        }
        if (wparam == VK_F6) {
            focus_address();
            return 0;
        }
        if (wparam == VK_ESCAPE) {
            send_control(4);
            return 0;
        }
        send_key((unsigned short)wparam, 1, 0);
        return 0;
    case WM_KEYUP:
        send_key((unsigned short)wparam, 2, 0);
        return 0;
    case WM_CHAR:
        if (wparam <= 255 && wparam >= 32) send_key(0, 3, (unsigned char)wparam);
        return 0;
    }
    return DefWindowProc(window, message, wparam, lparam);
}

static LRESULT CALLBACK main_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    char status[256];
    char dialog_message[2049];
    char dialog_default[1025];
    char dialog_result[1025];
    unsigned char dialog_kind;
    int dialog_accepted;
    unsigned char ack[4];
    switch (message) {
    case WM_CREATE:
        CreateWindow("BUTTON", "Back", WS_CHILD | WS_VISIBLE | WS_TABSTOP, 4, 5, 48, 24,
                     window, (HMENU)ID_BACK, NULL, NULL);
        CreateWindow("BUTTON", "Forward", WS_CHILD | WS_VISIBLE | WS_TABSTOP, 54, 5, 55, 24,
                     window, (HMENU)ID_FORWARD, NULL, NULL);
        CreateWindow("BUTTON", "Reload", WS_CHILD | WS_VISIBLE | WS_TABSTOP, 111, 5, 50, 24,
                     window, (HMENU)ID_RELOAD, NULL, NULL);
        CreateWindow("BUTTON", "Stop", WS_CHILD | WS_VISIBLE | WS_TABSTOP, 163, 5, 42, 24,
                     window, (HMENU)ID_STOP, NULL, NULL);
        g_address = CreateWindowEx(WS_EX_CLIENTEDGE, "EDIT", "",
                     WS_CHILD | WS_VISIBLE | WS_TABSTOP | ES_AUTOHSCROLL, 209, 6, 385, 22,
                     window, (HMENU)ID_ADDRESS, NULL, NULL);
        g_old_edit_proc = (WNDPROC)SetWindowLong(g_address, GWL_WNDPROC, (LONG)address_proc);
        CreateWindow("BUTTON", "Go", WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_DEFPUSHBUTTON,
                     598, 5, 42, 24, window, (HMENU)ID_GO, NULL, NULL);
        g_view = CreateWindowEx(WS_EX_CLIENTEDGE, "RetroBridgeView", "",
                     WS_CHILD | WS_VISIBLE | WS_TABSTOP, 4, 34, VIEW_WIDTH, VIEW_HEIGHT,
                     window, (HMENU)ID_VIEW, NULL, NULL);
        g_status = CreateWindowEx(WS_EX_CLIENTEDGE, "STATIC", "Starting...",
                     WS_CHILD | WS_VISIBLE | SS_LEFT, 4, 518, VIEW_WIDTH, 20,
                     window, (HMENU)ID_STATUS, NULL, NULL);
        return 0;
    case WM_COMMAND:
        if (LOWORD(wparam) >= ID_FAVORITE_FIRST && LOWORD(wparam) <= ID_FAVORITE_LAST) {
            open_favorite(LOWORD(wparam));
            return 0;
        }
        switch (LOWORD(wparam)) {
        case ID_BACK: send_control(1); break;
        case ID_FORWARD: send_control(2); break;
        case ID_RELOAD: send_control(3); break;
        case ID_STOP: send_control(4); break;
        case ID_GO: send_navigation(); break;
        case ID_FILE_DOWNLOADS:
            DialogBox(g_instance, MAKEINTRESOURCE(IDD_DOWNLOAD_HISTORY), window,
                      downloads_proc);
            break;
        case ID_FILE_EXIT: DestroyWindow(window); break;
        case ID_EDIT_COPY: send_clipboard_request(RB_CLIPBOARD_COPY); break;
        case ID_EDIT_CUT: send_clipboard_request(RB_CLIPBOARD_CUT); break;
        case ID_EDIT_PASTE: paste_guest_clipboard(); break;
        case ID_EDIT_SELECT_ALL:
            send_key(VK_CONTROL, 1, 0);
            send_key('A', 1, 0);
            send_key('A', 2, 0);
            send_key(VK_CONTROL, 2, 0);
            break;
        case ID_EDIT_FIND: show_find_window(); break;
        case ID_VIEW_HOME: send_control(5); break;
        case ID_VIEW_RELOAD: send_control(3); break;
        case ID_VIEW_STOP: send_control(4); break;
        case ID_GO_ADDRESS: focus_address(); break;
        case ID_GO_BACK: send_control(1); break;
        case ID_GO_FORWARD: send_control(2); break;
        case ID_FAVORITE_ADD: add_current_favorite(); break;
        case ID_FAVORITE_MANAGE:
            DialogBox(g_instance, MAKEINTRESOURCE(IDD_FAVORITES), window, favorites_proc);
            break;
        case ID_HELP_DIAGNOSTICS:
            {
                char diagnostic[768];
                char host_version[64];
                if (g_have_host_version)
                    wsprintf(host_version, "%u.%u.%u", g_host_version[0],
                             g_host_version[1], g_host_version[2]);
                else
                    lstrcpy(host_version, "Legacy / not reported");
                wsprintf(diagnostic,
                    "Client: 0.3.0\r\nRenderer: %s (%s:%d)\r\n"
                    "Connection: %s\r\nCodec: RGB565/LZ4\r\n"
                    "Capabilities: 0x%08lX",
                    host_version,
                    g_server, g_port, g_authenticated ? "Connected" : "Disconnected",
                    g_capabilities);
                MessageBox(window, diagnostic, "RetroBridge98 Diagnostics",
                           MB_OK | MB_ICONINFORMATION);
            }
            break;
        case ID_HELP_ABOUT:
            MessageBox(window,
                "RetroBridge98 0.3.0\r\n\r\nModern web rendering for Windows 98, powered by an "
                "isolated Chromium session on the native host.\r\n\r\nDo not enter sensitive credentials.",
                "About RetroBridge98", MB_OK | MB_ICONINFORMATION);
            break;
        }
        return 0;
    case WM_RB_STATUS:
        EnterCriticalSection(&g_status_lock);
        lstrcpyn(status, g_status_text, sizeof(status));
        LeaveCriticalSection(&g_status_lock);
        SetWindowText(g_status, status);
        return 0;
    case WM_RB_FRAME:
        InvalidateRect(g_view, NULL, FALSE);
        UpdateWindow(g_view);
        rb_put_u32(ack, (unsigned long)wparam);
        queue_message(RB_MSG_FRAME_ACK, ack, sizeof(ack));
        return 0;
    case WM_RB_DIALOG:
        EnterCriticalSection(&g_dialog_lock);
        dialog_kind = g_dialog_kind;
        lstrcpyn(dialog_message, g_dialog_message, sizeof(dialog_message));
        lstrcpyn(dialog_default, g_dialog_default, sizeof(dialog_default));
        LeaveCriticalSection(&g_dialog_lock);
        dialog_result[0] = 0;
        if (dialog_kind == 1) {
            MessageBox(window, dialog_message, "Page message", MB_OK | MB_ICONINFORMATION);
            dialog_accepted = TRUE;
        } else if (dialog_kind == 2) {
            dialog_accepted = MessageBox(window, dialog_message, "Page question",
                                         MB_OKCANCEL | MB_ICONQUESTION) == IDOK;
        } else {
            dialog_accepted = show_text_prompt("Page prompt", dialog_message, dialog_default,
                                               dialog_result, sizeof(dialog_result));
        }
        EnterCriticalSection(&g_dialog_lock);
        g_dialog_accepted = dialog_accepted;
        if (dialog_accepted && dialog_kind == 3)
            lstrcpyn(g_dialog_response, dialog_result, sizeof(g_dialog_response));
        LeaveCriticalSection(&g_dialog_lock);
        SetEvent(g_dialog_event);
        return 0;
    case WM_RB_DISCONNECTED:
        SetWindowText(window, "RetroBridge98");
        return 0;
    case WM_DESTROY:
        g_quit = TRUE;
        if (g_dialog_event != NULL) SetEvent(g_dialog_event);
        EnterCriticalSection(&g_socket_lock);
        if (g_socket != INVALID_SOCKET) shutdown(g_socket, 2);
        LeaveCriticalSection(&g_socket_lock);
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProc(window, message, wparam, lparam);
}

int WINAPI WinMain(HINSTANCE instance, HINSTANCE previous, LPSTR command, int show)
{
    WNDCLASS window_class;
    WNDCLASS view_class;
    WNDCLASS find_class;
    WSADATA winsock;
    MSG message;
    DWORD thread_id;
    (void)previous;
    (void)command;
    g_instance = instance;
    InitializeCriticalSection(&g_frame_lock);
    InitializeCriticalSection(&g_socket_lock);
    InitializeCriticalSection(&g_queue_lock);
    InitializeCriticalSection(&g_status_lock);
    InitializeCriticalSection(&g_dialog_lock);
    InitializeCriticalSection(&g_history_lock);
    g_dialog_event = CreateEvent(NULL, TRUE, FALSE, NULL);
    if (g_dialog_event == NULL) {
        MessageBox(NULL, "Could not create the page-dialog event.",
                   "RetroBridge98", MB_OK | MB_ICONERROR);
        return 1;
    }
    g_front = (unsigned char *)GlobalAlloc(GMEM_FIXED, FRAME_BYTES);
    g_back = (unsigned char *)GlobalAlloc(GMEM_FIXED, FRAME_BYTES);
    g_compressed = (unsigned char *)GlobalAlloc(GMEM_FIXED, COMPRESSED_BYTES);
    if (g_front == NULL || g_back == NULL || g_compressed == NULL) {
        MessageBox(NULL, "Not enough memory for the 640x480 frame buffers.",
                   "RetroBridge98", MB_OK | MB_ICONERROR);
        return 1;
    }
    load_configuration();
    load_favorites();
    if (!valid_token() || g_port <= 0 || g_port > 65535) {
        MessageBox(NULL, "RETROBRIDGE.INI is missing a valid pairing token.",
                   "RetroBridge98", MB_OK | MB_ICONERROR);
        return 1;
    }
    if (WSAStartup(MAKEWORD(1, 1), &winsock) != 0) {
        MessageBox(NULL, "Winsock 1.1 is not installed or configured.",
                   "RetroBridge98", MB_OK | MB_ICONERROR);
        return 1;
    }
    memset(&view_class, 0, sizeof(view_class));
    view_class.style = CS_HREDRAW | CS_VREDRAW | CS_DBLCLKS;
    view_class.lpfnWndProc = view_proc;
    view_class.hInstance = instance;
    view_class.hCursor = LoadCursor(NULL, IDC_ARROW);
    view_class.lpszClassName = "RetroBridgeView";
    RegisterClass(&view_class);
    memset(&find_class, 0, sizeof(find_class));
    find_class.style = CS_HREDRAW | CS_VREDRAW;
    find_class.lpfnWndProc = find_proc;
    find_class.hInstance = instance;
    find_class.hCursor = LoadCursor(NULL, IDC_ARROW);
    find_class.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    find_class.lpszClassName = "RetroBridgeFind";
    RegisterClass(&find_class);
    memset(&window_class, 0, sizeof(window_class));
    window_class.style = CS_HREDRAW | CS_VREDRAW;
    window_class.lpfnWndProc = main_proc;
    window_class.hInstance = instance;
    window_class.hIcon = LoadIcon(NULL, IDI_APPLICATION);
    window_class.hCursor = LoadCursor(NULL, IDC_ARROW);
    window_class.hbrBackground = (HBRUSH)(COLOR_BTNFACE + 1);
    window_class.lpszClassName = "RetroBridge98";
    RegisterClass(&window_class);
    g_main = CreateWindow("RetroBridge98", "RetroBridge98",
                          WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
                          CW_USEDEFAULT, CW_USEDEFAULT, 656, 580,
                          NULL, create_main_menu(), instance, NULL);
    if (g_main == NULL) return 1;
    ShowWindow(g_main, show);
    UpdateWindow(g_main);
    rebuild_favorites_menu();
    SetFocus(g_address);
    g_thread = CreateThread(NULL, 0, network_thread, NULL, 0, &thread_id);
    if (g_thread == NULL) {
        char error[96];
        wsprintf(error, "CreateThread failed with error %lu.", GetLastError());
        MessageBox(NULL, error, "RetroBridge98", MB_OK | MB_ICONERROR);
    }
    while (GetMessage(&message, NULL, 0, 0)) {
        if (message.message == WM_KEYDOWN) {
            if (message.wParam == VK_F5) {
                send_control(3);
                continue;
            }
            if (message.wParam == VK_F6) {
                focus_address();
                continue;
            }
            if (message.wParam == VK_ESCAPE) {
                if (g_find_window != NULL && IsWindowVisible(g_find_window)) {
                    ShowWindow(g_find_window, SW_HIDE);
                    SetFocus(g_view);
                } else {
                    send_control(4);
                }
                continue;
            }
            if ((GetKeyState(VK_MENU) & 0x8000) && message.wParam == VK_LEFT) {
                send_control(1);
                continue;
            }
            if ((GetKeyState(VK_MENU) & 0x8000) && message.wParam == VK_RIGHT) {
                send_control(2);
                continue;
            }
        }
        if (message.message == WM_KEYDOWN && (GetKeyState(VK_CONTROL) & 0x8000)) {
            if (message.wParam == 'L') {
                focus_address();
                continue;
            }
            if (message.wParam == 'F') {
                show_find_window();
                continue;
            }
        }
        TranslateMessage(&message);
        DispatchMessage(&message);
    }
    if (g_thread != NULL) {
        if (WaitForSingleObject(g_thread, 5000) == WAIT_TIMEOUT) {
            CloseHandle(g_thread);
            return (int)message.wParam;
        }
        CloseHandle(g_thread);
    }
    WSACleanup();
    GlobalFree(g_front);
    GlobalFree(g_back);
    GlobalFree(g_compressed);
    CloseHandle(g_dialog_event);
    DeleteCriticalSection(&g_history_lock);
    DeleteCriticalSection(&g_dialog_lock);
    DeleteCriticalSection(&g_status_lock);
    DeleteCriticalSection(&g_queue_lock);
    DeleteCriticalSection(&g_socket_lock);
    DeleteCriticalSection(&g_frame_lock);
    return (int)message.wParam;
}
