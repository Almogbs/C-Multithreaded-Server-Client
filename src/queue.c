#include <stdio.h>
#include <stdlib.h>
#include "segel.h"
#include "queue.h"


typedef struct queue {
	int front, rear, capacity;
	ConnVar* arr;
} *Queue;


Queue queueCreate(int capacity) {
	Queue q = malloc(sizeof(*q));
	if(!q) {
		return NULL;
	}
	q->front = - 1;
	q->rear = -1;
	q->capacity = capacity;
	q->arr = malloc(capacity*sizeof(*q->arr));
	return q;
}
void queueDestroy(Queue q) {
	if (q) {
		while (!queueIsEmpty(q))
		{
			ConnVar del = queueFront(q);
			queueDequeue(q);
			Close(del->connfd);
			free(del);
		}
		free(q->arr);
		free(q);
	}	
}

int queueIsFull(Queue q) {
	return ((q->front == q->rear + 1) || (q->front == 0 && q->rear == q->capacity - 1));
}

int queueIsEmpty(Queue q) {
	return  q->front == -1;
}

void queueEnqueue(Queue q, ConnVar x) {
	if (queueIsFull(q)) {
		return;
	}
	if(queueIsEmpty(q)) q->front = 0;
	q->rear = (q->rear + 1) % q->capacity;
	q->arr[q->rear] = x;
}

void queueDequeue(Queue q) {
	if (queueIsEmpty(q)) {
		return;
	}
	if (q->front == q->rear) {
		q->front = -1;
		q->rear = -1;
	}
	else {
		q->front = (q->front + 1) % q->capacity;
	}
}

ConnVar queueFront(Queue q) {
	if (queueIsEmpty(q)) {
		return NULL;
	}
	return q->arr[q->front];
}


