/**
 * Sample C module for testing tree-sitter parser
 */

#include <stdio.h>
#include <stdlib.h>
#include <string.h>

/**
 * Person structure
 */
typedef struct {
    char name[100];
    int age;
} Person;

/**
 * Create a new person
 */
Person* person_create(const char* name, int age) {
    Person* p = (Person*)malloc(sizeof(Person));
    if (p != NULL) {
        strncpy(p->name, name, 99);
        p->name[99] = '\0';
        p->age = age;
    }
    return p;
}

/**
 * Get greeting message
 */
void person_greet(const Person* p, char* buffer, size_t size) {
    if (p != NULL && buffer != NULL) {
        snprintf(buffer, size, "Hello, my name is %s", p->name);
    }
}

/**
 * Increment age
 */
void person_celebrate_birthday(Person* p) {
    if (p != NULL) {
        p->age++;
    }
}

/**
 * Calculator structure
 */
typedef struct {
    double* history;
    size_t count;
    size_t capacity;
} Calculator;

/**
 * Create a new calculator
 */
Calculator* calculator_create(void) {
    Calculator* calc = (Calculator*)malloc(sizeof(Calculator));
    if (calc != NULL) {
        calc->capacity = 10;
        calc->history = (double*)malloc(calc->capacity * sizeof(double));
        calc->count = 0;
    }
    return calc;
}

/**
 * Add two numbers
 */
double calculator_add(Calculator* calc, double a, double b) {
    if (calc == NULL) return 0.0;
    double result = a + b;
    // Add to history (simplified)
    return result;
}

/**
 * Subtract b from a
 */
double calculator_subtract(Calculator* calc, double a, double b) {
    if (calc == NULL) return 0.0;
    double result = a - b;
    return result;
}

/**
 * Free calculator
 */
void calculator_free(Calculator* calc) {
    if (calc != NULL) {
        free(calc->history);
        free(calc);
    }
}

/**
 * Standalone function to process data
 */
int process_strings(char** input, int count, char** output) {
    for (int i = 0; i < count; i++) {
        // Convert to uppercase (simplified)
        output[i] = strdup(input[i]);
    }
    return count;
}
