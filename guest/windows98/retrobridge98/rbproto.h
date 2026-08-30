#ifndef RBPROTO_H
#define RBPROTO_H

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <winsock.h>

#define RB_MAGIC "RB98"
#define RB_VERSION 1
#define RB_HEADER_SIZE 12
#define RB_MAX_PAYLOAD (2UL * 1024UL * 1024UL)
#define RB_TOKEN_LENGTH 32

#define RB_MSG_HELLO 1
#define RB_MSG_WELCOME 2
#define RB_MSG_NAVIGATE 3
#define RB_MSG_CONTROL 4
#define RB_MSG_POINTER 5
#define RB_MSG_KEY 6
#define RB_MSG_FRAME 7
#define RB_MSG_FRAME_ACK 8
#define RB_MSG_STATUS 9
#define RB_MSG_ERROR 10
#define RB_MSG_PING 11
#define RB_MSG_PONG 12
#define RB_MSG_FIND 13
#define RB_MSG_CLIPBOARD 14
#define RB_MSG_DIALOG 15
#define RB_MSG_DIALOG_REPLY 16
#define RB_MSG_DOWNLOAD 17
#define RB_MSG_CAPABILITIES 18
#define RB_MSG_PEER_INFO 19
#define RB_MSG_FAVORITES_STATE 20
#define RB_MSG_DOWNLOAD_HISTORY_REQUEST 21
#define RB_MSG_DOWNLOAD_HISTORY 22

#define RB_CAP_CLIPBOARD 2UL
#define RB_CAP_PEER_INFO 32UL
#define RB_CAP_FAVORITES_SYNC 64UL
#define RB_CAP_DOWNLOAD_HISTORY 128UL

#define RB_DOWNLOAD_COMPLETE 1
#define RB_DOWNLOAD_OVERSIZE 2
#define RB_DOWNLOAD_FAILED 3
#define RB_DOWNLOAD_BLOCKED 4

#define RB_CLIPBOARD_COPY 1
#define RB_CLIPBOARD_CUT 2
#define RB_CLIPBOARD_PASTE 3
#define RB_CLIPBOARD_RESULT 4

#define RB_PIXEL_RGB565_LZ4 2

typedef struct rb_header {
    unsigned short version;
    unsigned short type;
    unsigned long length;
} rb_header;

int rb_send_all(SOCKET sock, const void *data, unsigned long length);
int rb_recv_all(SOCKET sock, void *data, unsigned long length);
int rb_send_packet(SOCKET sock, unsigned short type, const void *payload, unsigned long length);
int rb_recv_header(SOCKET sock, rb_header *header);
void rb_put_u16(unsigned char *target, unsigned short value);
void rb_put_u32(unsigned char *target, unsigned long value);
unsigned short rb_get_u16(const unsigned char *source);
unsigned long rb_get_u32(const unsigned char *source);

#endif
