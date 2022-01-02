#ifndef __QUEUE_H__
#define __QUEUE_H__


typedef struct queue *Queue;

typedef struct conn_var_t
{
    int connfd;
    struct timeval arrive_time;
    struct timeval dispatch_time;
} *ConnVar;


Queue queueCreate(int capacity);
void queueDestroy(Queue q);
int queueIsFull(Queue q);
int queueIsEmpty(Queue q);
void queueEnqueue(Queue q, ConnVar x);
void queueDequeue(Queue q);
ConnVar queueFront(Queue q);

#endif /*  __QUEUE_H__  */
