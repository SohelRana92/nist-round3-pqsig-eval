#ifndef PQG_LOCALE_H
#define PQG_LOCALE_H
/* Declared only: used by printing code that verification never reaches. */
char *setlocale(int category, const char *locale);
#define LC_ALL 6
#define LC_NUMERIC 4
#endif
