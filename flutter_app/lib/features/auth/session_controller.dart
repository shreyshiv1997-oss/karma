import 'package:flutter/foundation.dart';

import '../../data/models/models.dart';
import '../../data/repositories/karma_repository.dart';

enum SessionStatus { loading, signedOut, signedIn }

class SessionController extends ChangeNotifier {
  SessionController(this._repository) {
    _repository.api.onAuthenticationLost = _authenticationLost;
  }

  final KarmaRepository _repository;

  SessionStatus _status = SessionStatus.loading;
  User? _user;
  int _userRevision = 0;

  SessionStatus get status => _status;
  User? get user => _user;

  Future<void> initialize() async {
    final int revision = ++_userRevision;
    try {
      final User? restored = await _repository.restoreUser();
      if (revision != _userRevision) return;
      _user = restored;
      _status = _user == null ? SessionStatus.signedOut : SessionStatus.signedIn;
    } on Object {
      if (revision != _userRevision) return;
      // A network failure is not proof that a credential is invalid. The auth
      // surface remains available and the secure token stays intact for retry.
      _status = SessionStatus.signedOut;
    }
    notifyListeners();
  }

  Future<void> login({required String identifier, required String password}) async {
    final int revision = ++_userRevision;
    final AuthResult result = await _repository.login(
      identifier: identifier,
      password: password,
    );
    if (revision != _userRevision) return;
    _user = result.user;
    _status = SessionStatus.signedIn;
    notifyListeners();
  }

  Future<void> register({
    required String handle,
    required String displayName,
    required String identifier,
    required String password,
    required String city,
  }) async {
    final int revision = ++_userRevision;
    final AuthResult result = await _repository.register(
      handle: handle,
      displayName: displayName,
      identifier: identifier,
      password: password,
      city: city,
    );
    if (revision != _userRevision) return;
    _user = result.user;
    _status = SessionStatus.signedIn;
    notifyListeners();
  }

  Future<void> refreshUser() async {
    final int revision = ++_userRevision;
    final User refreshed = await _repository.currentUser();
    if (revision != _userRevision || _status != SessionStatus.signedIn) return;
    _user = refreshed;
    notifyListeners();
  }

  Future<void> replaceUser(User user) async {
    _userRevision += 1;
    _user = user;
    _status = SessionStatus.signedIn;
    notifyListeners();
  }

  Future<void> logout() async {
    _userRevision += 1;
    await _repository.logout();
    _user = null;
    _status = SessionStatus.signedOut;
    notifyListeners();
  }

  void _authenticationLost() {
    _userRevision += 1;
    _user = null;
    _status = SessionStatus.signedOut;
    notifyListeners();
  }
}
