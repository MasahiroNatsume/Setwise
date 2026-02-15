import 'dart:async';

import 'package:dio/dio.dart';
import 'package:flutter/foundation.dart';

class ApiService {
  // Optional override:
  // flutter run --dart-define=API_BASE_URL=http://192.168.1.20:8000
  static const String _overrideBaseUrl =
      String.fromEnvironment('API_BASE_URL', defaultValue: '');

  static String get baseUrl {
    if (_overrideBaseUrl.isNotEmpty) return _overrideBaseUrl;

    // Android emulator -> host machine localhost
    if (!kIsWeb && defaultTargetPlatform == TargetPlatform.android) {
      return 'http://10.0.2.2:8000';
    }

    // Windows/macOS/Linux/Web local run
    return 'http://127.0.0.1:8000';
  }

  final Dio _dio = Dio(
    BaseOptions(
      baseUrl: baseUrl,
      connectTimeout: const Duration(seconds: 60),
      receiveTimeout: const Duration(seconds: 120),
    ),
  );

  bool _isTransientNetworkError(Object e) {
    if (e is! DioException) return false;
    final code = e.type;
    final msg = (e.message ?? '').toLowerCase();
    return code == DioExceptionType.connectionTimeout ||
        code == DioExceptionType.receiveTimeout ||
        code == DioExceptionType.connectionError ||
        msg.contains('semaphore timeout') ||
        msg.contains('timed out');
  }

  static String resolveAudioUrl(String rawPath) {
    if (rawPath.startsWith('http://') || rawPath.startsWith('https://')) {
      return rawPath;
    }
    if (rawPath.startsWith('/')) {
      return '$baseUrl$rawPath';
    }
    return '$baseUrl/$rawPath';
  }

  Future<Map<String, dynamic>> upsertUserProfile({
    required String userId,
    required String category,
    required List<String> tags,
  }) async {
    final response = await _dio.put(
      '/users/$userId/profile',
      data: {
        'category': category,
        'tags': tags,
      },
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> createJob({
    required String topic,
    int topK = 3,
    int maxArticles = 15,
    String? ttsProvider,
    String? ttsVoice,
    double? ttsSpeed,
  }) async {
    final body = <String, dynamic>{
      'topic': topic,
      'top_k': topK,
      'max_articles': maxArticles,
    };
    if (ttsProvider != null && ttsProvider.isNotEmpty) {
      body['tts_provider'] = ttsProvider;
    }
    if (ttsVoice != null && ttsVoice.isNotEmpty) {
      body['tts_voice'] = ttsVoice;
    }
    if (ttsSpeed != null) {
      body['tts_speed'] = ttsSpeed;
    }
    final response = await _dio.post(
      '/jobs/create',
      data: body,
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> getJobStatus(String jobId) async {
    final response = await _dio.get('/jobs/$jobId');
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> getFeed({
    required String userId,
    int limit = 20,
    double explorationRatio = 0.2,
  }) async {
    final response = await _dio.get(
      '/feed/$userId',
      queryParameters: {
        'limit': limit,
        'exploration_ratio': explorationRatio,
      },
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  Future<Map<String, dynamic>> trackEvent({
    required String userId,
    required String episodeId,
    required String eventType,
    Map<String, dynamic>? metadata,
  }) async {
    final response = await _dio.post(
      '/events/track',
      data: {
        'user_id': userId,
        'episode_id': episodeId,
        'event_type': eventType,
        'timestamp': DateTime.now().toUtc().toIso8601String(),
        'metadata': metadata ?? {},
      },
    );
    return Map<String, dynamic>.from(response.data as Map);
  }

  // Compatibility helper for previous flow: submit job then poll until done.
  Future<Map<String, dynamic>> generatePodcast(String topic) async {
    final created = await createJob(topic: topic);
    final jobId = created['job_id'] as String;

    const maxPoll = 240; // up to ~12 minutes with 3s interval
    for (var i = 0; i < maxPoll; i++) {
      Map<String, dynamic>? status;
      var retries = 0;
      while (status == null && retries < 3) {
        try {
          status = await getJobStatus(jobId);
        } catch (e) {
          retries += 1;
          if (!_isTransientNetworkError(e) || retries >= 3) rethrow;
          await Future<void>.delayed(const Duration(seconds: 2));
        }
      }
      if (status == null) {
        throw Exception('Job status check failed');
      }

      final state = status['status'] as String? ?? 'queued';
      if (state == 'completed') {
        final result = status['result'] as Map<String, dynamic>? ?? {};
        return {
          'status': 'success',
          'job_id': jobId,
          ...result,
        };
      }
      if (state == 'failed') {
        throw Exception(status['error'] ?? 'Job failed');
      }
      await Future<void>.delayed(const Duration(seconds: 3));
    }
    throw Exception('Job polling timed out');
  }
}
