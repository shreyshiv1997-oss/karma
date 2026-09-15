import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import '../../core/theme/app_theme.dart';
import '../../data/repositories/karma_repository.dart';
import '../../shared/widgets/primitives.dart';
import 'session_controller.dart';

enum _AuthMode { signIn, createAccount }

class AuthScreen extends StatefulWidget {
  const AuthScreen({super.key});

  @override
  State<AuthScreen> createState() => _AuthScreenState();
}

class _AuthScreenState extends State<AuthScreen> {
  final GlobalKey<FormState> _formKey = GlobalKey<FormState>();
  final TextEditingController _identifier = TextEditingController(text: 'priya');
  final TextEditingController _password = TextEditingController(text: 'StrongPass!234');
  final TextEditingController _handle = TextEditingController();
  final TextEditingController _name = TextEditingController();
  final TextEditingController _city = TextEditingController(text: 'Indore');
  final TextEditingController _otp = TextEditingController();

  _AuthMode _mode = _AuthMode.signIn;
  bool _busy = false;
  bool _obscure = true;
  bool _otpSent = false;
  String? _devOtp;
  String? _error;

  bool get _isPhoneRegistration =>
      _mode == _AuthMode.createAccount && !_identifier.text.contains('@');

  @override
  void dispose() {
    _identifier.dispose();
    _password.dispose();
    _handle.dispose();
    _name.dispose();
    _city.dispose();
    _otp.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    setState(() {
      _busy = true;
      _error = null;
    });

    try {
      if (_mode == _AuthMode.signIn) {
        await context.read<SessionController>().login(
              identifier: _identifier.text,
              password: _password.text,
            );
      } else if (_isPhoneRegistration && !_otpSent) {
        final String? code = await context
            .read<KarmaRepository>()
            .sendOtp(_identifier.text);
        if (!mounted) return;
        setState(() {
          _otpSent = true;
          _devOtp = code;
          if (code != null) _otp.text = code;
        });
      } else {
        if (_isPhoneRegistration) {
          await context.read<KarmaRepository>().verifyOtp(
                phone: _identifier.text,
                otp: _otp.text,
              );
        }
        if (!mounted) return;
        await context.read<SessionController>().register(
              handle: _handle.text,
              displayName: _name.text,
              identifier: _identifier.text,
              password: _password.text,
              city: _city.text,
            );
      }
    } on Object catch (error) {
      if (!mounted) return;
      setState(() => _error = errorMessage(error));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  void _setMode(_AuthMode value) {
    setState(() {
      _mode = value;
      _error = null;
      _otpSent = false;
      _devOtp = null;
      if (value == _AuthMode.signIn && _identifier.text.isEmpty) {
        _identifier.text = 'priya';
      } else if (value == _AuthMode.createAccount && _identifier.text == 'priya') {
        _identifier.clear();
        _password.clear();
      }
    });
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: AppColors.ink,
        body: Stack(
          children: <Widget>[
            const Positioned(
              right: -110,
              top: -90,
              child: _AmbientRing(size: 300, color: AppColors.violet),
            ),
            const Positioned(
              left: -90,
              bottom: -130,
              child: _AmbientRing(size: 280, color: AppColors.gold),
            ),
            SafeArea(
              child: Center(
                child: SingleChildScrollView(
                  padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 28),
                  child: ConstrainedBox(
                    constraints: const BoxConstraints(maxWidth: 430),
                    child: Column(
                      children: <Widget>[
                        const KarmaRing(value: 88, size: 66),
                        const SizedBox(height: 14),
                        Text(
                          'KARMA',
                          style: Theme.of(context).textTheme.displaySmall?.copyWith(
                                color: Colors.white,
                                fontSize: 35,
                              ),
                        ),
                        const SizedBox(height: 4),
                        const Text(
                          'Thou art the work you do.',
                          style: TextStyle(
                            color: Color(0xFFA5A29A),
                            fontSize: 15,
                          ),
                        ),
                        const SizedBox(height: 28),
                        Material(
                          color: AppColors.surface,
                          borderRadius: BorderRadius.circular(22),
                          clipBehavior: Clip.antiAlias,
                          child: Padding(
                            padding: const EdgeInsets.all(22),
                            child: Form(
                              key: _formKey,
                              autovalidateMode: AutovalidateMode.onUserInteraction,
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.stretch,
                                children: <Widget>[
                                  _ModePicker(mode: _mode, onChanged: _setMode),
                                  const SizedBox(height: 20),
                                  if (_mode == _AuthMode.createAccount) ...<Widget>[
                                    TextFormField(
                                      controller: _name,
                                      textCapitalization: TextCapitalization.words,
                                      textInputAction: TextInputAction.next,
                                      autofillHints: const <String>[AutofillHints.name],
                                      decoration: const InputDecoration(
                                        labelText: 'Name',
                                        hintText: 'Priya Malviya',
                                        prefixIcon: Icon(Icons.person_outline_rounded),
                                      ),
                                      validator: _required,
                                    ),
                                    const SizedBox(height: 12),
                                    TextFormField(
                                      controller: _handle,
                                      textInputAction: TextInputAction.next,
                                      autocorrect: false,
                                      decoration: const InputDecoration(
                                        labelText: 'Handle',
                                        hintText: 'your.name',
                                        prefixIcon: Icon(Icons.alternate_email_rounded),
                                      ),
                                      validator: (String? value) {
                                        final String input = value?.trim() ?? '';
                                        if (!RegExp(r'^[a-z0-9_.]{3,30}$').hasMatch(input)) {
                                          return 'Use 3–30 lowercase letters, numbers, . or _';
                                        }
                                        return null;
                                      },
                                    ),
                                    const SizedBox(height: 12),
                                  ],
                                  TextFormField(
                                    controller: _identifier,
                                    textInputAction: TextInputAction.next,
                                    keyboardType: _mode == _AuthMode.createAccount
                                        ? TextInputType.emailAddress
                                        : TextInputType.text,
                                    autofillHints: const <String>[AutofillHints.username],
                                    onChanged: (_) {
                                      if (_otpSent) {
                                        setState(() {
                                          _otpSent = false;
                                          _devOtp = null;
                                          _otp.clear();
                                        });
                                      }
                                    },
                                    decoration: InputDecoration(
                                      labelText: _mode == _AuthMode.signIn
                                          ? 'Handle, email or phone'
                                          : 'Email or phone',
                                      hintText: _mode == _AuthMode.signIn
                                          ? 'priya'
                                          : 'you@example.com',
                                      prefixIcon: const Icon(Icons.badge_outlined),
                                    ),
                                    validator: (String? value) {
                                      if ((value?.trim().length ?? 0) < 3) {
                                        return 'Enter your handle, email or phone';
                                      }
                                      return null;
                                    },
                                  ),
                                  if (_otpSent) ...<Widget>[
                                    const SizedBox(height: 12),
                                    TextFormField(
                                      controller: _otp,
                                      keyboardType: TextInputType.number,
                                      textInputAction: TextInputAction.next,
                                      autofillHints: const <String>[
                                        AutofillHints.oneTimeCode,
                                      ],
                                      maxLength: 8,
                                      decoration: const InputDecoration(
                                        labelText: 'Verification code',
                                        prefixIcon: Icon(Icons.sms_outlined),
                                        counterText: '',
                                      ),
                                      validator: (String? value) {
                                        if ((value?.trim().length ?? 0) < 4) {
                                          return 'Enter the code sent to your phone';
                                        }
                                        return null;
                                      },
                                    ),
                                    if (_devOtp != null) ...<Widget>[
                                      const SizedBox(height: 6),
                                      Text(
                                        'Development code: $_devOtp',
                                        style: const TextStyle(
                                          color: AppColors.gold,
                                          fontSize: 12.5,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                                    ],
                                  ],
                                  const SizedBox(height: 12),
                                  TextFormField(
                                    controller: _password,
                                    obscureText: _obscure,
                                    textInputAction: _mode == _AuthMode.signIn
                                        ? TextInputAction.done
                                        : TextInputAction.next,
                                    autofillHints: <String>[
                                      _mode == _AuthMode.signIn
                                          ? AutofillHints.password
                                          : AutofillHints.newPassword,
                                    ],
                                    onFieldSubmitted: (_) {
                                      if (_mode == _AuthMode.signIn) _submit();
                                    },
                                    decoration: InputDecoration(
                                      labelText: 'Password',
                                      prefixIcon: const Icon(Icons.lock_outline_rounded),
                                      suffixIcon: IconButton(
                                        tooltip: _obscure ? 'Show password' : 'Hide password',
                                        onPressed: () => setState(() => _obscure = !_obscure),
                                        icon: Icon(
                                          _obscure
                                              ? Icons.visibility_outlined
                                              : Icons.visibility_off_outlined,
                                        ),
                                      ),
                                    ),
                                    validator: (String? value) {
                                      final int minimum =
                                          _mode == _AuthMode.signIn ? 1 : 8;
                                      if ((value?.length ?? 0) < minimum) {
                                        return _mode == _AuthMode.signIn
                                            ? 'Enter your password'
                                            : 'Use at least 8 characters';
                                      }
                                      return null;
                                    },
                                  ),
                                  if (_mode == _AuthMode.createAccount) ...<Widget>[
                                    const SizedBox(height: 12),
                                    TextFormField(
                                      controller: _city,
                                      textCapitalization: TextCapitalization.words,
                                      textInputAction: TextInputAction.done,
                                      onFieldSubmitted: (_) => _submit(),
                                      decoration: const InputDecoration(
                                        labelText: 'City',
                                        prefixIcon: Icon(Icons.location_city_outlined),
                                      ),
                                      validator: _required,
                                    ),
                                  ],
                                  if (_error != null) ...<Widget>[
                                    const SizedBox(height: 14),
                                    Semantics(
                                      liveRegion: true,
                                      child: Text(
                                        _error!,
                                        style: const TextStyle(
                                          color: AppColors.rose,
                                          fontWeight: FontWeight.w600,
                                        ),
                                      ),
                                    ),
                                  ],
                                  const SizedBox(height: 18),
                                  FilledButton(
                                    onPressed: _busy ? null : _submit,
                                    child: _busy
                                        ? const SizedBox.square(
                                            dimension: 21,
                                            child: CircularProgressIndicator(
                                              strokeWidth: 2.5,
                                              color: Colors.white,
                                            ),
                                          )
                                        : Text(_buttonLabel),
                                  ),
                                  if (_mode == _AuthMode.signIn) ...<Widget>[
                                    const SizedBox(height: 18),
                                    const Row(
                                      children: <Widget>[
                                        Expanded(child: Divider()),
                                        Padding(
                                          padding: EdgeInsets.symmetric(horizontal: 10),
                                          child: Text(
                                            'DEMO',
                                            style: TextStyle(
                                              color: AppColors.textFaint,
                                              fontSize: 10,
                                              fontWeight: FontWeight.w800,
                                              letterSpacing: 1,
                                            ),
                                          ),
                                        ),
                                        Expanded(child: Divider()),
                                      ],
                                    ),
                                    const SizedBox(height: 10),
                                    Wrap(
                                      alignment: WrapAlignment.center,
                                      spacing: 8,
                                      runSpacing: 8,
                                      children: <Widget>[
                                        ActionChip(
                                          avatar: const Icon(Icons.home_repair_service, size: 17),
                                          label: const Text('Customer · Priya'),
                                          onPressed: () => _fillDemo('priya'),
                                        ),
                                        ActionChip(
                                          avatar: const Icon(Icons.electric_bolt, size: 17),
                                          label: const Text('Worker · Ramesh'),
                                          onPressed: () => _fillDemo('ramesh.electric'),
                                        ),
                                      ],
                                    ),
                                  ],
                                ],
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(height: 16),
                        const Text(
                          'One identity. Hire today, take work tomorrow.',
                          textAlign: TextAlign.center,
                          style: TextStyle(color: Color(0xFFA5A29A), fontSize: 12.5),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ),
          ],
        ),
      );

  String get _buttonLabel {
    if (_mode == _AuthMode.signIn) return 'Sign in';
    if (_isPhoneRegistration && !_otpSent) return 'Send verification code';
    return 'Create account';
  }

  void _fillDemo(String handle) {
    setState(() {
      _identifier.text = handle;
      _password.text = 'StrongPass!234';
      _error = null;
    });
  }

  static String? _required(String? value) =>
      (value?.trim().isEmpty ?? true) ? 'This field is required' : null;
}

class _ModePicker extends StatelessWidget {
  const _ModePicker({required this.mode, required this.onChanged});

  final _AuthMode mode;
  final ValueChanged<_AuthMode> onChanged;

  @override
  Widget build(BuildContext context) => SegmentedButton<_AuthMode>(
        showSelectedIcon: false,
        segments: const <ButtonSegment<_AuthMode>>[
          ButtonSegment<_AuthMode>(
            value: _AuthMode.signIn,
            label: Text('Sign in'),
          ),
          ButtonSegment<_AuthMode>(
            value: _AuthMode.createAccount,
            label: Text('Create account'),
          ),
        ],
        selected: <_AuthMode>{mode},
        onSelectionChanged: (Set<_AuthMode> value) => onChanged(value.first),
        style: ButtonStyle(
          visualDensity: VisualDensity.comfortable,
          minimumSize: const WidgetStatePropertyAll<Size>(Size(0, 46)),
          side: const WidgetStatePropertyAll<BorderSide>(
            BorderSide(color: AppColors.line),
          ),
        ),
      );
}

class _AmbientRing extends StatelessWidget {
  const _AmbientRing({required this.size, required this.color});

  final double size;
  final Color color;

  @override
  Widget build(BuildContext context) => ExcludeSemantics(
        child: Container(
          width: size,
          height: size,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            border: Border.all(color: color.withValues(alpha: 0.13), width: 44),
          ),
        ),
      );
}
