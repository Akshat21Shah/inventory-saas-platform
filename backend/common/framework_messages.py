"""The framework's own messages people can see (Django REST framework's field errors), listed so
our catalogs translate them too (ADR-060). Our ``locale`` folder comes first in Django's
lookup, so these translations replace the framework's (DRF has no Hindi or Marathi).

Exactly the framework's English text, placeholders included ({max_length} etc. are filled in
by the framework after translation). Never called: ``gettext_noop`` only marks them.
"""

from django.utils.translation import gettext_noop

FIELD_ERRORS = (
    gettext_noop("This field is required."),
    gettext_noop("This field may not be null."),
    gettext_noop("This field may not be blank."),
    gettext_noop("Not a valid string."),
    gettext_noop("Ensure this field has no more than {max_length} characters."),
    gettext_noop("Ensure this field has at least {min_length} characters."),
    gettext_noop("Enter a valid email address."),
    gettext_noop("This value does not match the required pattern."),
    gettext_noop("Must be a valid UUID."),
    gettext_noop("Must be a valid boolean."),
    gettext_noop("A valid integer is required."),
    gettext_noop("A valid number is required."),
    gettext_noop("Ensure this value is less than or equal to {max_value}."),
    gettext_noop("Ensure this value is greater than or equal to {min_value}."),
    gettext_noop("Ensure that there are no more than {max_digits} digits in total."),
    gettext_noop("Ensure that there are no more than {max_decimal_places} decimal places."),
    gettext_noop(
        "Ensure that there are no more than {max_whole_digits} digits before the decimal point."
    ),
    gettext_noop("Date has wrong format. Use one of these formats instead: {format}."),
    gettext_noop("Datetime has wrong format. Use one of these formats instead: {format}."),
    gettext_noop("Time has wrong format. Use one of these formats instead: {format}."),
    gettext_noop('"{input}" is not a valid choice.'),
    gettext_noop('Expected a list of items but got type "{input_type}".'),
    gettext_noop("This list may not be empty."),
    gettext_noop("This selection may not be empty."),
    gettext_noop("Ensure this field has no more than {max_length} elements."),
    gettext_noop('Invalid pk "{pk_value}" - object does not exist.'),
    gettext_noop("No file was submitted."),
    gettext_noop("The submitted file is empty."),
    gettext_noop(
        "Upload a valid image. The file you uploaded was either not an image or a corrupted image."
    ),
    gettext_noop("Invalid data. Expected a dictionary, but got {datatype}."),
    gettext_noop("Authentication credentials were not provided."),
    gettext_noop("You do not have permission to perform this action."),
    gettext_noop("Not found."),
    gettext_noop("Request was throttled."),
    gettext_noop("Malformed request."),
)
