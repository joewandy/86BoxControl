#include "rbproto.h"
#include <string.h>

void rb_put_u16(unsigned char *target, unsigned short value)
{
    target[0] = (unsigned char)(value & 255U);
    target[1] = (unsigned char)((value >> 8) & 255U);
}

void rb_put_u32(unsigned char *target, unsigned long value)
{
    target[0] = (unsigned char)(value & 255UL);
    target[1] = (unsigned char)((value >> 8) & 255UL);
    target[2] = (unsigned char)((value >> 16) & 255UL);
    target[3] = (unsigned char)((value >> 24) & 255UL);
}

unsigned short rb_get_u16(const unsigned char *source)
{
    return (unsigned short)(source[0] | ((unsigned short)source[1] << 8));
}

unsigned long rb_get_u32(const unsigned char *source)
{
    return (unsigned long)source[0] |
           ((unsigned long)source[1] << 8) |
           ((unsigned long)source[2] << 16) |
           ((unsigned long)source[3] << 24);
}

int rb_send_all(SOCKET sock, const void *data, unsigned long length)
{
    const char *cursor = (const char *)data;
    int amount;
    while (length > 0) {
        amount = send(sock, cursor, length > 32767UL ? 32767 : (int)length, 0);
        if (amount == SOCKET_ERROR || amount == 0) return 0;
        cursor += amount;
        length -= (unsigned long)amount;
    }
    return 1;
}

int rb_recv_all(SOCKET sock, void *data, unsigned long length)
{
    char *cursor = (char *)data;
    int amount;
    while (length > 0) {
        amount = recv(sock, cursor, length > 32767UL ? 32767 : (int)length, 0);
        if (amount == SOCKET_ERROR || amount == 0) return 0;
        cursor += amount;
        length -= (unsigned long)amount;
    }
    return 1;
}

int rb_send_packet(SOCKET sock, unsigned short type, const void *payload, unsigned long length)
{
    unsigned char header[RB_HEADER_SIZE];
    if (length > RB_MAX_PAYLOAD) return 0;
    memcpy(header, RB_MAGIC, 4);
    rb_put_u16(header + 4, RB_VERSION);
    rb_put_u16(header + 6, type);
    rb_put_u32(header + 8, length);
    if (!rb_send_all(sock, header, RB_HEADER_SIZE)) return 0;
    if (length > 0 && !rb_send_all(sock, payload, length)) return 0;
    return 1;
}

int rb_recv_header(SOCKET sock, rb_header *header)
{
    unsigned char raw[RB_HEADER_SIZE];
    if (!rb_recv_all(sock, raw, RB_HEADER_SIZE)) return 0;
    if (memcmp(raw, RB_MAGIC, 4) != 0) return 0;
    header->version = rb_get_u16(raw + 4);
    header->type = rb_get_u16(raw + 6);
    header->length = rb_get_u32(raw + 8);
    if (header->version != RB_VERSION || header->length > RB_MAX_PAYLOAD) return 0;
    return 1;
}
