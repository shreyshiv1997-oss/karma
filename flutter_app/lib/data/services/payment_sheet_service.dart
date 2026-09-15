import 'package:flutter/material.dart';
import 'package:flutter_stripe/flutter_stripe.dart';

import '../models/models.dart';
import '../repositories/karma_repository.dart';

bool isPaymentSheetCancellation(Object error) =>
    error is StripeException &&
    error.error.code.toString().toLowerCase().contains('cancel');

/// Keeps card data inside Stripe's native PaymentSheet.
///
/// KARMA's API returns only a PaymentIntent client secret and publishable key. A PaymentSheet
/// success is never treated as payment truth: the service asks the backend to retrieve the
/// PaymentIntent from Stripe before allowing work to begin.
class PaymentSheetService {
  const PaymentSheetService(this._repository);

  final KarmaRepository _repository;

  Future<GigPayment> secure(int gigId) async {
    GigPayment payment = await _repository.secureGigPayment(gigId);
    if (payment.isSecured) return payment;

    final String? clientSecret = payment.clientSecret;
    final String? publishableKey = payment.publishableKey;
    if (clientSecret == null || publishableKey == null) {
      throw StateError('Stripe payment setup is incomplete. Please try again.');
    }

    Stripe.publishableKey = publishableKey;
    Stripe.urlScheme = 'karma';
    await Stripe.instance.applySettings();
    await Stripe.instance.initPaymentSheet(
      paymentSheetParameters: SetupPaymentSheetParameters(
        paymentIntentClientSecret: clientSecret,
        merchantDisplayName: 'KARMA',
        returnURL: 'karma://stripe-redirect',
        style: ThemeMode.system,
      ),
    );
    await Stripe.instance.presentPaymentSheet();

    // Do not trust the client-side success animation. The backend retrieves Stripe's
    // authoritative status and accepts only requires_capture/succeeded.
    payment = await _repository.syncGigPayment(gigId);
    if (!payment.isSecured) {
      throw StateError(
        payment.failureMessage ??
            'Stripe is still processing this payment. Pull to refresh in a moment.',
      );
    }
    return payment;
  }

  Future<GigPayment> release(int gigId) => _repository.releaseGigPayment(gigId);
}
