import json
import logging
import time
from typing import Any, Tuple, Dict

import firebase_admin
from django.contrib.auth import get_user_model, authenticate
from django.contrib.auth.models import User
from django.contrib.auth.validators import ASCIIUsernameValidator
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction, IntegrityError
from django.db.models import QuerySet
from firebase_admin import messaging
from firebase_admin.exceptions import InvalidArgumentError
from rest_framework.authtoken.models import Token
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response

from v2.models import FCMTokens, Friend

logger = logging.getLogger(__name__)


@api_view(['POST'])
def register_device(request: Request) -> Response:
    """
    POST: Registers a device for receiving alerts for an account.

    Requires `fcm_token` parameter to be set to the Firebase Cloud Messaging token to use for that device

    Requires authentication.

    Returns status 400 if the token is already registered to the account
    Returns status 200 otherwise
    No data is returned.
    """
    good, response = check_params(['fcm_token'], request.data)
    if not good:
        return response

    try:
        with transaction.atomic():
            FCMTokens.objects.create(user=request.user, fcm_token=request.data['fcm_token'])
    except IntegrityError:
        return Response(build_response(False, 'That token is already registered'), status=400)
    return Response(build_response(True, 'Token successfully registered'), status=200)


@api_view(['POST'])
@permission_classes([AllowAny])
def register_user(request: Request) -> Response:
    """
    POST: Registers a new user account with the provided credentials

    Requires `first_name`, `last_name`, `username`, and `password`. Optionally accepts `email` as well. Username will be
    a unique identifier for the user. Email is currently not used, but may at some point be used for password reset/MFA/
    account alerts.

    Does not require authentication.

    If the username is already taken: returns status 400 with message "Username taken"
    Otherwise: status 200
    Returns no data.
    """
    good, response = check_params(['first_name', 'last_name', 'username', 'password'], request.data)
    if not good:
        return response
    if len(request.data['password']) < 8:
        return Response(build_response(False, 'Password must be at least 8 characters'), status=400)
    try:
        if 'email' in request.data:
            validate_email(request.data.get('email'))
        with transaction.atomic():
            ASCIIUsernameValidator()(request.data['username'])
            get_user_model().objects.create_user(first_name=request.data['first_name'],
                                                 last_name=request.data['last_name'],
                                                 username=request.data['username'],
                                                 password=request.data['password'],
                                                 email=request.data.get('email'))
    except IntegrityError:
        return Response(build_response(False, 'Username taken'), status=400)
    except ValidationError as e:
        return Response(build_response(False, e.message), status=400)
    return Response(build_response(True, 'User created'), status=200)


@api_view(['POST'])
def add_friend(request: Request) -> Response:
    """
    POST: Adds a user as a friend of the authenticated user. This allows the other user to send messages to the authenticated
    user, but not the other way around (unless that user adds this user as a friend).

    Requires the `username` parameter to be set.

    Requires authentication.

    Returns no data.
    """
    good, response = check_params(['username'], request.data)
    if not good:
        return response

    try:
        friend = get_user_model().objects.get(username=request.data['username'])
        Friend.objects.update_or_create(owner=request.user, friend=friend, defaults={
            'deleted': False})
        return Response(build_response(True, 'Successfully added/restored friend'), status=200)
    except IntegrityError:
        return Response(build_response(False, 'An error occurred when restoring friend'), status=400)
    except get_user_model().DoesNotExist:
        return Response(build_response(False, 'User does not exist'), status=400)


@api_view(['PUT'])
def edit_friend_name(request: Request) -> Response:
    """
    PUT: Edits the name this user has associated with their friend

    Every user can give each of their friends a custom name - only the user can see this, not the friend or anyone
    else (think of this like giving your friend a contact name). Thus, the relationship between users can be
    represented as a directed graph, with each user as a vertex, and friend relationships as edges between the
    vertices. The label of each edge is the friend name, only visible to the parent of the edge.

    user1 --[user1's name for user2]--> user2
    user2 --[user2's name for user1]--> user1
    There doesn't necessarily need to be a symmetric relationship between users: user1 ---> user2 but no edge from
    user2 to user1

    Requires `username` - this is the username of the friend - and `new_name` - this is the name to give them.

    If `username` is not a friend of the authenticated user, a friend relationship is created to store the
    information but it is marked as deleted.

    Requires authentication

    Returns no data
    """
    good, response = check_params(['username', 'new_name'], request.data)
    if not good:
        return response

    try:
        friend = get_user_model().objects.get(username=request.data['username'])
        rel, created = Friend.objects.update_or_create(owner=request.user, friend=friend,
                                                       defaults={'name': request.data['new_name']})
        if created:
            rel.deleted = True
            rel.save()
        return Response(build_response(True, 'Successfully updated friend name'), status=200)
    except IntegrityError:
        return Response(build_response(False, 'An error occurred when changing friend\'s name'), status=400)
    except get_user_model().DoesNotExist:
        return Response(build_response(False, 'An error occurred when restoring friend'), status=400)


@api_view(['GET', 'HEAD'])
def get_friend_name(request: Request) -> Response:
    """
    GET: Gets the name corresponding to a particular username.

    Requires the `username` parameter.

    Requires authentication.

    Returns the following data:
    {
        name: <user's name>
    }
    """
    good, response = check_params(['username'], request.query_params)
    if not good:
        return response

    try:
        friend = get_user_model().objects.get(username=request.query_params['username'])
        try:
            rel = Friend.objects.get(owner=request.user, friend=friend)
            return Response(build_response(True, 'Got name', {'name': rel.name}), status=200)
        except Friend.DoesNotExist:
            return Response(build_response(True, 'Got name', {'name': f'{friend.first_name} {friend.last_name}'}),
                            status=200)
    except get_user_model().DoesNotExist:
        return Response(build_response(False, "Couldn't find user"), status=400)


@api_view(['DELETE'])
def delete_friend(request: Request) -> Response:
    """
    DELETE: This friend relationship will be lazy-deleted, and can be fully undone by adding the friend back.

    Requires the `friend` parameter to be set to a current friend of the authenticated user.

    Requires authentication.

    Returns status 400 if the other user is not a friend, and no data.
    """
    good, response = check_params(['friend'], request.data)
    if not good:
        return response

    try:
        with transaction.atomic():
            friend = Friend.objects.select_for_update().get(owner=request.user, friend__username=request.data['friend'])
            friend.deleted = True
            friend.save()
        return Response(build_response(True, 'Successfully deleted friend'), status=200)
    except Friend.DoesNotExist:
        return Response(build_response(False, 'Could not delete friend as you were not friends'), status=400)


@api_view(['DELETE'])
def delete_user_data(request: Request) -> Response:
    """
    DELETE: Truly deletes all data associated with the authenticated user (not lazy deletion, cannot be
    undone). Includes references to the user other people have in their friend lists, etc.

    Requires `username` and `password` in addition to an authentication token.

    Requires authentication.

    Returns no data.
    """
    good, response = check_params(['username', 'password'], request.data)
    if not good:
        return response

    user = authenticate(username=request.data['username'], password=request.data['password'])
    if request.user.username != request.data['username'] or user is None:
        return Response(build_response(False, 'Forbidden'), status=403)

    get_user_model().objects.get(username=request.user.username).delete()
    return Response(build_response(True, 'Successfully deleted user data'), status=200)


@api_view(['PUT'])
def edit_user(request: Request) -> Response:
    """
    PUT: Updates the corresponding fields for the authenticated user.

    Has 4 optional parameters: `first_name`, `last_name`, `email`, `password`, and `old_password`. If `password` is
    provided, `old_password` must also be provided (returning status 400 if it is not), and it should be the password
    the user currently has - otherwise, will return status 403.

    Requires authentication.

    Returns no data.
    """
    updated = True
    invalid_field = []
    user = get_user_model().objects.select_for_update().get(username=request.user.username)
    if 'first_name' in request.data:
        user.first_name = request.data['first_name']
    if 'last_name' in request.data:
        user.last_name = request.data['last_name']
    if 'email' in request.data:
        try:
            validate_email(request.data['email'])
            user.email = request.data['email']
        except ValidationError:
            updated = False
            invalid_field.append('email')
            logger.info('Invalid email provided to update')
    if 'password' in request.data and updated:  # this check needs to come last
        if len(request.data['password']) >= 8 and 'old_password' in request.data:
            check_pass = authenticate(username=request.user.username, password=request.data['old_password'])
            if check_pass is not None:
                user.set_password(request.data['password'])
                Token.objects.get(user=user).delete()
            else:
                return Response(build_response(False, 'Incorrect old password'), status=403)
        else:
            updated = False
            invalid_field.append('password')
    if updated:
        user.save()
        return Response(build_response(True, 'User updated successfully'), status=200)
    if not updated:
        return Response(build_response(False, f'Could not update user: invalid value for {",".join(invalid_field)}'),
                        status=400)


@api_view(['GET', 'HEAD'])
def get_user_info(request: Request) -> Response:
    """
    GET: Returns a data dump based on the user used to authenticate.

    Accepts no parameters.

    Requires authentication.

    On success, returns the following in the data field:
    {
        username: <user's username>,
        first_name: <user's first name>,
        last_name: <user's last name>,
        email: <user's email>,
        friends: [
            {
                friend: <friend's username>,
                name: <friend's name>,
                sent: <number of messages sent to friend>,
                received: <number of messages received from friend>,
                last_message_id_sent: <the last alert id that was sent to this friend>,
                last_message_read: <whether the last message was read or not>
            },
            ...
        ]
    }
    """
    user = request.user
    friends = [flatten_friend(x) for x in Friend.objects.filter(owner=user)]
    data = {
        'username': user.username,
        'first_name': user.first_name,
        'last_name': user.last_name,
        'email': user.email,
        'friends': friends,
    }
    return Response(build_response(True, 'Got user data', data=data), status=200)


@api_view(['POST'])
def send_alert(request: Request) -> Response:
    """
    POST: Sends an alert with an optional message to a user. The user must have the authenticated user added as a friend
    for this to succeed.

    Requires `to` and `message` to be set as parameters. If `message` is 'null', the app should display the default "no
    message" alert.

    Requires authentication.

    Returns status 400 on error
    On success, returns the following data:
    {
        'id': <alert id>
    }
    """
    # unauthenticated requests should be denied automatically - test this
    good, response = check_params(['to', 'message'], request.data)
    if not good:
        return response

    to: str = request.data['to']

    alert_id = str(time.time())
    try:
        friend = Friend.objects.get(owner__username=to, friend__username=request.user.username, deleted=False)
        friend.received += 1
        friend.save()
        friend, created = Friend.objects.get_or_create(owner__username=request.user.username, friend__username=to,
                                                       defaults={'deleted': True})
        friend.sent += 1
        friend.last_sent_alert_id = alert_id
        friend.last_sent_message_read = False
        friend.save()
    except Friend.DoesNotExist:
        return Response(build_response(False, f'Could not send message as {to} does not have you as a friend'),
                        status=403)

    tokens: QuerySet = FCMTokens.objects.filter(user__username=to)
    if not bool(tokens):
        return Response(build_response(False, f'Could not find user {to}'), status=400)
    try:
        firebase_admin.initialize_app()
    except ValueError:
        logger.info('Firebase Admin app already initialized')

    at_least_one_success: bool = False
    for token in tokens:
        message = messaging.Message(
            data={
                'action': 'alert',
                'alert_id': alert_id,
                'alert_to': request.data['to'],
                'alert_from': request.user.username,
                'alert_message': request.data['message']
            },
            android=messaging.AndroidConfig(
                priority='high'
            ),
            token=token
        )

        try:
            response = messaging.send(message)
            at_least_one_success = True
        except InvalidArgumentError as e:
            logger.warning(f'An alert failed to send: {e.cause}')

    if not at_least_one_success:
        return Response(build_response(False, f"Unable to send message"), status=400)
    return Response(build_response(True, "Successfully sent message", data={'id': alert_id}), status=200)


@api_view(['POST'])
def alert_read(request: Request) -> Response:
    """
    POST: Sends a signal to dismiss an alert on all of the user's other devices.

    Requires `alert_id`, `from`, and `fcm_token` parameters to be set.

    Requires authentication.

    Returns no data.
    """
    good, response = check_params(['alert_id', 'from', 'fcm_token'], request.data)
    if not good:
        return response

    friends_read = Friend.objects.filter(owner__username=request.data['from'],
                                         last_sent_alert_id=request.data['alert_id'])
    for friend in friends_read:
        friend.last_sent_message_read = True
        friend.save()

    tokens: QuerySet = FCMTokens.objects.filter(user__username=request.data['from']).exclude(fcm_token=request.data[
        'fcm_token']).union(FCMTokens.objects.filter(user__username=request.user.username))

    if not bool(tokens):
        logger.warning("Could not find tokens for recipient or the users other devices")
        return Response(build_response(False, f'An error occurred'), status=500)
    try:
        firebase_admin.initialize_app()
    except ValueError:
        logger.info('Firebase Admin app already initialized')

    at_least_one_success: bool = False
    alert_id = time.time()
    for token in tokens:
        message = messaging.Message(
            data={
                'action': 'read',
                'alert_id': alert_id,
                'username_to': request.user.username,
            },
            android=messaging.AndroidConfig(
                priority='low'
            ),
            token=token
        )

        try:
            response = messaging.send(message)
            at_least_one_success = True
        except InvalidArgumentError as e:
            logger.warning(f'An alert failed to send: {e.cause}')

    if not at_least_one_success:
        return Response(build_response(False, f"Unable to send read status"), status=400)
    return Response(build_response(True, "Successfully sent read status"), status=200)


def check_params(expected: list, holder: Dict) -> Tuple[bool, Response]:
    missing: list = []
    for expect in expected:
        if expect not in holder:
            missing.append(expect)
    response = Response(build_response(False, f"Missing required parameter(s): {', '.join(missing)}"),
                        status=400) if len(missing) != 0 else Response()
    return len(missing) == 0, response


def build_response(success: bool, message: str, data: Any = None, string: bool = False) -> dict:
    response = {
        "success": success,
        "message": message,
        "data": data
    }
    if string:
        response = string_response(response)
    return response


def string_response(args: dict):
    return json.dumps(args)

def flatten_friend(friend: Friend):
    return {
        'friend': friend.friend.username,
        'name': friend.name or f'{friend.friend.first_name} {friend.friend.last_name}',
        'sent': friend.sent,
        'received': friend.received,
        'last_message_id_sent': friend.last_sent_alert_id,
        'last_message_read': friend.last_sent_message_read,
    }
